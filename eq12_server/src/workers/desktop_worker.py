"""
DesktopWorker —— 桌面操作 worker：让机器人操控它所在的这台 Windows 电脑
========================================================================

EQ12「硅基生命」跑在桌面 Windows 主机上：这台电脑就是它的"身体外的工具"。
本 worker 用 pyautogui 在同一会话里模拟键盘 / 鼠标 / 滚轮，用 Pillow 截屏，
用 Win32 剪切板 API 写剪切板，让上游（brain）能"看屏幕 → 想 → 操作"。

与飞书一样是**进程内 worker，不走 MQTT**，收发各一条内部队列（在 main_loop
里与 asr/tts 同级创建，'_' 前缀 = 纯内部队列，不被 stop() 哨兵 / 专职发送
线程接管）：

    _sub/desktop   收 / 出：屏幕截图 + 指令完成回执（本 worker 放进来，下游消费）
    _pub/desktop   发 / 入：电脑控制指令（上游放进来，本 worker 消费并执行）

_pub/desktop 指令格式：

    {"type": "keyboard", "value": "A",  "time": 3}
        # 同时按下 value 里的所有键并保持 time 秒（time 缺省 = 轻点一下）。
        # 组合键直接拼写，如 "AZ" = A 和 Z 一起按；特殊键用名字，如
        #   "CTRLALTDELETE" = Ctrl+Alt+Delete、"SHIFTA" = 带 Shift 的 A。
        # ⚠️ 名字按【最长匹配】切分：LEFT/ENTER/SPACE/F10… 会优先被识别成
        #   一个特殊键而不是拆成单字母（所以想按"上箭头"写 LEFT，不是 L+E+F+T）。
        #   字母/数字/标点按物理键发送，大小写靠显式 SHIFT 组合（如 "SHIFTA"）。
    {"type": "mouse",  "direction": "UP|DOWN|LEFT|RIGHT", "value": 12}
        # 鼠标从当前位置相对移动 value 像素。
    {"type": "scroll", "direction": "UP|DOWN", "value": 12}
        # 滚轮滚动 value 格（UP 向上 / DOWN 向下，一格=一个滚轮刻度）。
    {"type": "screenshot"}                                   # 无其它字段
        # 截一张全屏 JPEG → 放进 _sub/desktop（仿 ESP32 的 pub/eye b'photo'
        # → sub/eye 照片：按需截，不常开流）。
    {"type": "clipboard", "value": "要写进剪切板的文字"}
        # 把 value 写进 Windows 剪切板（空串 = 清空）。配合
        #   {"type":"keyboard","value":"CTRLV"} 就能把这段文字粘到别处。
        # value 必须是字符串；其它类型一律判无效。

_sub/desktop 截图载荷（字段对齐 esp32 的 sub/eye 照片 JSON，只是多了 fmt）：

    {'type': 'screen', 'time': <unix 秒>, 'size': <JPEG 字节数>,
     'width': W, 'height': H, 'fmt': 'jpeg', 'data': '<base64 JPEG>'}

完成回执（本 worker 每**真正执行成功**一条指令就追加一条，与截图同队列、按序，
下游统一消费 _sub/desktop 即可）：

    {'type': 'done', 'time': <unix 秒>, 'command': <原始指令 dict>}
        # 说明刚完成的指令：keyboard 已按完抬起 / mouse 已移动 / scroll 已滚 /
        #   screenshot 已把截图入队（紧随其后的那条 {'type':'screen'} 即结果）/
        #   clipboard 已写入剪切板。
        # 只回"真做完"的：指令无效（缺参/方向错/无按键）或执行抛异常只打日志，
        #   不回执——下游如需配对/超时兜底，用 type 区分 screen / done。

依赖：
    pip install pyautogui Pillow   # 键鼠/滚轮 + 截屏；硬依赖，缺了直接 import 报错
    （剪切板用 ctypes 调 Win32 API，不加新依赖）

说明：
    - 本 worker 执行的是 OS 级键鼠指令，等同真人在操作电脑；只消费 _pub/desktop
      队列里明确下发的指令，不做任何自主判断。
    - 自动关掉 pyautogui 的 FailSafe（默认鼠标到屏幕四角会抛异常退出）：机器人
      需要能点屏幕角上的关闭按钮/开始菜单，四角触发会误伤。
    - 按住组合键期间若某键 keyDown 失败，finally 会把已按下的键全部抬起，
      避免键盘卡键。
"""

from __future__ import annotations

import base64
import io
import re
import time
from queue import Queue

import pyautogui as _pyautogui
from PIL import Image as _PIL_Image   # 截图后 JPEG 编码用（pyautogui 截屏本身也要它）

from ..config import (DESKTOP_HOLD_S, DESKTOP_JPEG_QUALITY,
                      QUEUE_DESKTOP_PUB, QUEUE_DESKTOP_SUB)

# 特殊键：大写规范名 -> pyautogui 键名（箭头/修饰键/编辑键等）。
# 切分按键串时对这些名字做最长匹配 —— "CTRLALTDELETE" 才能正确切成
# CTRL+ALT+DELETE 而不是拆成单个字母。
_KEY_ALIAS = {
    'ENTER': 'enter', 'RETURN': 'enter',
    'SPACE': 'space', 'TAB': 'tab',
    'ESC': 'esc', 'ESCAPE': 'esc',
    'BACKSPACE': 'backspace', 'DELETE': 'delete',
    'INSERT': 'insert', 'HOME': 'home', 'END': 'end',
    'PAGEUP': 'pageup', 'PGUP': 'pageup',
    'PAGEDOWN': 'pagedown', 'PGDN': 'pagedown',
    'LEFT': 'left', 'RIGHT': 'right', 'UP': 'up', 'DOWN': 'down',
    'CTRL': 'ctrl', 'CONTROL': 'ctrl',
    'ALT': 'alt', 'SHIFT': 'shift',
    'WIN': 'win', 'META': 'win', 'CMD': 'win', 'COMMAND': 'win',
    'CAPSLOCK': 'capslock', 'CAPS': 'capslock',
    'NUMLOCK': 'numlock', 'SCROLLLOCK': 'scrolllock',
    'PRINTSCREEN': 'printscreen', 'PRTSC': 'printscreen',
    'PAUSE': 'pause', 'BREAK': 'break',
}
_SPECIAL_SORTED = sorted(_KEY_ALIAS, key=len, reverse=True)   # 最长匹配用
_FKEY_RE = re.compile(r'F(?:2[0-4]|1[0-9]|[1-9])')            # F1..F24(位数长优先)

_MOUSE_STEP = {'UP': (0, -1), 'DOWN': (0, 1),
               'LEFT': (-1, 0), 'RIGHT': (1, 0)}

# ---------------------------------------------------------------- 剪切板
# 用 Win32 API 写剪切板，不引入新依赖：
#   - pyperclip 要多装一个包；
#   - tkinter 有线程亲和性问题，而本 worker 跑在 worker 线程里。
_CF_UNICODETEXT = 13
_GMEM_MOVEABLE = 0x0002
_CLIP_TRIES = 5          # OpenClipboard 会被别的进程短暂占用，重试几次
_CLIP_RETRY_WAIT = 0.05  # 每次重试间隔（秒）

try:
    import ctypes
    from ctypes import wintypes

    _user32 = ctypes.WinDLL('user32', use_last_error=True)
    _kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)

    _user32.OpenClipboard.argtypes = [wintypes.HWND]
    _user32.OpenClipboard.restype = wintypes.BOOL
    _user32.EmptyClipboard.restype = wintypes.BOOL
    _user32.CloseClipboard.restype = wintypes.BOOL
    _user32.SetClipboardData.argtypes = [wintypes.UINT, wintypes.HANDLE]
    _user32.SetClipboardData.restype = wintypes.HANDLE
    _kernel32.GlobalAlloc.argtypes = [wintypes.UINT, ctypes.c_size_t]
    _kernel32.GlobalAlloc.restype = wintypes.HANDLE
    _kernel32.GlobalLock.argtypes = [wintypes.HANDLE]
    _kernel32.GlobalLock.restype = ctypes.c_void_p
    _kernel32.GlobalUnlock.argtypes = [wintypes.HANDLE]
    _kernel32.GlobalFree.argtypes = [wintypes.HANDLE]
    _CLIPBOARD_OK = True
except Exception:                     # 非 Windows / 加载失败：功能降级，不影响其余
    _user32 = _kernel32 = None
    _CLIPBOARD_OK = False


def set_clipboard_text(text):
    """把 text 写进 Windows 剪切板；成功 True，失败 False（不抛异常）。

    调用方拿 False 时按"指令失败"处理 —— 与其它 desktop 指令一致：
    失败只打日志、不回执。
    """
    if not _CLIPBOARD_OK:
        print('[Desktop] 剪切板不可用（非 Windows 或 Win32 加载失败）', flush=True)
        return False

    for attempt in range(_CLIP_TRIES):
        if _user32.OpenClipboard(None):
            break
        time.sleep(_CLIP_RETRY_WAIT)   # 被别的进程占用，等一下再试
    else:
        print('[Desktop] OpenClipboard 失败（剪切板被占用）', flush=True)
        return False

    handle = None
    try:
        if not _user32.EmptyClipboard():
            print('[Desktop] EmptyClipboard 失败', flush=True)
            return False

        buf = ctypes.create_unicode_buffer(text)
        size = ctypes.sizeof(buf)      # 含结尾 NUL，CF_UNICODETEXT 要的就是这个
        handle = _kernel32.GlobalAlloc(_GMEM_MOVEABLE, size)
        if not handle:
            print('[Desktop] GlobalAlloc 失败', flush=True)
            return False

        ptr = _kernel32.GlobalLock(handle)
        if not ptr:
            print('[Desktop] GlobalLock 失败', flush=True)
            _kernel32.GlobalFree(handle)
            return False
        try:
            ctypes.memmove(ptr, buf, size)
        finally:
            _kernel32.GlobalUnlock(handle)

        # ⚠️ SetClipboardData 成功后这块内存归系统所有，不能再 GlobalFree
        if not _user32.SetClipboardData(_CF_UNICODETEXT, handle):
            print('[Desktop] SetClipboardData 失败', flush=True)
            _kernel32.GlobalFree(handle)
            return False
        handle = None                  # 移交成功，交出去
        return True
    except Exception as e:
        print('[Desktop] 写剪切板异常[%s]: %s' % (type(e).__name__, e), flush=True)
        if handle:
            _kernel32.GlobalFree(handle)
        return False
    finally:
        _user32.CloseClipboard()


def split_keys(value):
    """把按键串按【最长匹配】切成大写规范 token 列表。

    >>> split_keys('AZ')            -> ['A', 'Z']
    >>> split_keys('CTRLALTDELETE') -> ['CTRL', 'ALT', 'DELETE']
    >>> split_keys('LEFT')          -> ['LEFT']          # 上箭头键，不是 L+E+F+T
    >>> split_keys('SHIFTA')        -> ['SHIFT', 'A']
    >>> split_keys('F10')           -> ['F10']           # 功能键，不是 F+1+0
    """
    s = (value or '').upper()
    tokens = []
    i, n = 0, len(s)
    while i < n:
        rest = s[i:]
        hit = None
        for name in _SPECIAL_SORTED:          # 先试特殊键（长名字优先）
            if rest.startswith(name):
                hit = name
                break
        if hit is None:
            m = _FKEY_RE.match(rest)          # 再试 F1..F24
            if m:
                hit = m.group(0)
        if hit is None:
            hit = rest[0]                     # 兜底：单字符（字母/数字/标点）
        tokens.append(hit)
        i += len(hit)
    return tokens


def key_name(token):
    """大写规范 token -> pyautogui 可识别的键名。"""
    alias = _KEY_ALIAS.get(token)
    if alias:
        return alias
    if len(token) == 1:
        return token.lower() if token.isalnum() else token
    return token.lower()                      # 兜底（F1..F24 等）


class DesktopWorker:
    """桌面操作 worker：消费 _pub/desktop 指令执行键鼠/滚轮/截屏。

    gui 可注入替身（默认 pyautogui 模块），测试时记录调用而不真动鼠标键盘。
    """

    def __init__(self, queues: dict[str, Queue], stop_token=None, gui=None):
        self.queues = queues
        self.stop_token = stop_token
        self.gui = gui if gui is not None else _pyautogui

    # ------------------------------------------------------------ 指令执行
    def run(self):
        missing = [k for k in (QUEUE_DESKTOP_SUB, QUEUE_DESKTOP_PUB)
                   if k not in self.queues]
        if missing:
            print('[Desktop] 缺少内部队列 %s：请在 main_loop.py 里创建'
                  % missing, flush=True)
            return
        # 机器人要能点屏幕四角的关闭按钮/开始菜单，关掉 FailSafe 的角触发
        try:
            if getattr(self.gui, 'FAILSAFE', None) is not None:
                self.gui.FAILSAFE = False
        except Exception:
            pass
        print('[Desktop] DesktopWorker 已启动'
              '（指令←消费 %s，结果/截图→入队 %s）'
              % (QUEUE_DESKTOP_PUB, QUEUE_DESKTOP_SUB),
              flush=True)
        while True:
            item = self.queues[QUEUE_DESKTOP_PUB].get()   # 阻塞等指令
            if self.stop_token is not None and item is self.stop_token:
                break
            if not isinstance(item, dict):
                print('[Desktop] 忽略未知指令: %r' % (item,), flush=True)
                continue
            mtype = item.get('type')
            ok = False
            try:
                if mtype == 'keyboard':
                    ok = self._do_keyboard(item)
                elif mtype == 'mouse':
                    ok = self._do_mouse(item)
                elif mtype == 'scroll':
                    ok = self._do_scroll(item)
                elif mtype == 'screenshot':
                    ok = self._do_screenshot()
                elif mtype == 'clipboard':
                    ok = self._do_clipboard(item)
                else:
                    print('[Desktop] 忽略未知指令类型: %r' % (mtype,),
                          flush=True)
            except Exception as e:
                ok = False
                print('[Desktop] 指令执行失败[%s]: %s'
                      % (type(e).__name__, e), flush=True)
            if ok:
                self._report_done(item)   # 真做完才回执（失败/无效不回执）

    # ------------------------------------------------------------ 键盘
    def _do_keyboard(self, cmd):
        value = str(cmd.get('value') or '').strip()
        t = cmd.get('time')
        try:
            hold = float(t) if t is not None else DESKTOP_HOLD_S
        except (TypeError, ValueError):
            hold = DESKTOP_HOLD_S
        if hold < 0:
            hold = 0.0
        tokens = split_keys(value)
        names = [key_name(tok) for tok in tokens]
        if not names:
            print('[Desktop] 键盘指令缺 value: %s' % cmd, flush=True)
            return False
        print('[Desktop] 键盘 %s ×%.2fs' % ('+'.join(names), hold), flush=True)
        self._chord(names, hold)
        return True

    def _chord(self, names, hold):
        """同时按下所有键 → 保持 hold 秒 → 全部抬起。

        中途失败也会把已按下的键抬起（finally），避免键盘卡键。
        """
        down = []
        try:
            for n in names:
                self.gui.keyDown(n)
                down.append(n)
            time.sleep(hold)
        finally:
            for n in reversed(down):
                try:
                    self.gui.keyUp(n)
                except Exception as e:
                    print('[Desktop] keyUp(%s) 失败: %s' % (n, e), flush=True)

    # ------------------------------------------------------------ 鼠标
    def _do_mouse(self, cmd):
        direction = str(cmd.get('direction') or '').upper()
        try:
            value = int(cmd.get('value') or 0)
        except (TypeError, ValueError):
            value = 0
        step = _MOUSE_STEP.get(direction)
        if step is None or value == 0:
            print('[Desktop] 鼠标指令无效: %s' % cmd, flush=True)
            return False
        dx, dy = step[0] * value, step[1] * value
        print('[Desktop] 鼠标移动 (%+d, %+d)' % (dx, dy), flush=True)
        self.gui.moveRel(dx, dy, duration=0.0)
        return True

    # ------------------------------------------------------------ 滚轮
    def _do_scroll(self, cmd):
        direction = str(cmd.get('direction') or '').upper()
        try:
            value = int(cmd.get('value') or 0)
        except (TypeError, ValueError):
            value = 0
        if direction == 'UP':
            amount = abs(value)
        elif direction == 'DOWN':
            amount = -abs(value)
        else:
            print('[Desktop] 滚轮指令无效: %s' % cmd, flush=True)
            return False
        print('[Desktop] 滚轮 %s %d 格' % (direction, abs(value)), flush=True)
        self.gui.scroll(amount)      # pyautogui: 正=上滚, 负=下滚
        return True

    # ------------------------------------------------------------ 截屏
    def _do_screenshot(self):
        im = self.gui.screenshot()           # pyautogui -> PIL Image
        buf = io.BytesIO()
        im.save(buf, 'JPEG', quality=DESKTOP_JPEG_QUALITY)
        jpg = buf.getvalue()
        meta = {
            'type': 'screen',
            'time': int(time.time()),
            'size': len(jpg),
            'width': getattr(im, 'width', 0),
            'height': getattr(im, 'height', 0),
            'fmt': 'jpeg',
            'data': base64.b64encode(jpg).decode('ascii'),
        }
        self.queues[QUEUE_DESKTOP_SUB].put(meta)
        print('[Desktop] 截图已入队 %s: %dx%d %dB (JPEG q=%d)'
              % (QUEUE_DESKTOP_SUB, meta['width'], meta['height'],
                 len(jpg), DESKTOP_JPEG_QUALITY), flush=True)
        return True

    # ------------------------------------------------------------ 剪切板
    def _do_clipboard(self, cmd):
        """把 cmd['value'] 写进剪切板。空串合法（= 清空剪切板）。"""
        text = cmd.get('value')
        if not isinstance(text, str):
            print('[Desktop] 剪切板指令缺 value（需字符串）: %s' % cmd, flush=True)
            return False
        if not set_clipboard_text(text):
            return False
        print('[Desktop] 剪切板已写入 %d 字: %s'
              % (len(text), text[:60]), flush=True)
        return True

    # ------------------------------------------------------------ 完成回执
    def _report_done(self, cmd):
        """指令执行成功后，把完成回执放进 _sub/desktop（与截图同队列、按序）。

        载荷 = {'type': 'done', 'time': <unix 秒>, 'command': <原始指令 dict>}，
        说明刚完成的是哪条指令。只回"真做完"的：无效/失败路径在 run() 里
        已跳过本方法（见文件头协议说明）。
        """
        meta = {
            'type': 'done',
            'time': int(time.time()),
            'command': cmd,
        }
        self.queues[QUEUE_DESKTOP_SUB].put(meta)
        print('[Desktop] 指令完成已入队 %s: %s' % (QUEUE_DESKTOP_SUB, cmd),
              flush=True)
