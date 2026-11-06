"""桌面操作 worker：消费 _pub/desktop 指令，执行键鼠 / 滚轮 / 截屏 / 剪切板，结果进 _sub/desktop。

载荷格式见 core/queues.md。
"""

from __future__ import annotations

import base64
import io
import re
import time
from queue import Queue

import pyautogui as _pyautogui
from PIL import Image as _PIL_Image   # 截图后 JPEG 编码（pyautogui 截屏本身也要它）

from ..config import (DESKTOP_HOLD_S, DESKTOP_JPEG_QUALITY,
                      QUEUE_DESKTOP_PUB, QUEUE_DESKTOP_SUB)

# 大写规范名 -> pyautogui 键名；切分按键串时按长度最长匹配
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
_FKEY_RE = re.compile(r'F(?:2[0-4]|1[0-9]|[1-9])')            # F1..F24，位数长优先

_MOUSE_STEP = {'UP': (0, -1), 'DOWN': (0, 1),
               'LEFT': (-1, 0), 'RIGHT': (1, 0)}

# 剪切板走 Win32：pyperclip 要多装包，tkinter 有线程亲和性问题
_CF_UNICODETEXT = 13
_GMEM_MOVEABLE = 0x0002
_CLIP_TRIES = 5          # OpenClipboard 会被别的进程短暂占用
_CLIP_RETRY_WAIT = 0.05

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
except Exception:                     # 非 Windows / 加载失败：剪切板降级，其余照常
    _user32 = _kernel32 = None
    _CLIPBOARD_OK = False


def set_clipboard_text(text):
    """写进 Windows 剪切板；成功 True，失败 False（不抛异常）。"""
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

        if not _user32.SetClipboardData(_CF_UNICODETEXT, handle):
            print('[Desktop] SetClipboardData 失败', flush=True)
            _kernel32.GlobalFree(handle)
            return False
        handle = None                  # 成功后内存归系统所有，不能再 GlobalFree
        return True
    except Exception as e:
        print('[Desktop] 写剪切板异常[%s]: %s' % (type(e).__name__, e), flush=True)
        if handle:
            _kernel32.GlobalFree(handle)
        return False
    finally:
        _user32.CloseClipboard()


def split_keys(value):
    """按键串按最长匹配切成大写 token：'CTRLALTDELETE' -> ['CTRL','ALT','DELETE']。"""
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
    """大写 token -> pyautogui 键名。"""
    alias = _KEY_ALIAS.get(token)
    if alias:
        return alias
    if len(token) == 1:
        return token.lower() if token.isalnum() else token
    return token.lower()                      # 兜底（F1..F24 等）


class DesktopWorker:
    def __init__(self, queues: dict[str, Queue], stop_token=None, gui=None):
        self.queues = queues
        self.stop_token = stop_token
        self.gui = gui if gui is not None else _pyautogui

    def run(self):
        missing = [k for k in (QUEUE_DESKTOP_SUB, QUEUE_DESKTOP_PUB)
                   if k not in self.queues]
        if missing:
            print('[Desktop] 缺少内部队列 %s：请在 main_loop.py 里创建'
                  % missing, flush=True)
            return
        try:                       # 机器人要能点屏幕四角，关掉 FailSafe
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
                self._report_done(item)   # 真做完才回执，失败/无效不回执

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
        """同时按下所有键 → 保持 hold 秒 → 全部抬起；中途失败也保证抬起。"""
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

    def _do_screenshot(self):
        im = self.gui.screenshot()           # pyautogui -> PIL Image
        buf = io.BytesIO()
        im.save(buf, 'JPEG', quality=DESKTOP_JPEG_QUALITY)
        jpg = buf.getvalue()
        meta = {
            'queue': QUEUE_DESKTOP_SUB,
            'type': 'screen',
            'data': base64.b64encode(jpg).decode('ascii'),
            'width': getattr(im, 'width', 0),
            'height': getattr(im, 'height', 0),
            'size': len(jpg),
            'fmt': 'jpeg',
            'time': time.strftime('%Y-%m-%d %H:%M:%S'),
        }
        self.queues[QUEUE_DESKTOP_SUB].put(meta)
        print('[Desktop] 截图已入队 %s: %dx%d %dB (JPEG q=%d)'
              % (QUEUE_DESKTOP_SUB, meta['width'], meta['height'],
                 len(jpg), DESKTOP_JPEG_QUALITY), flush=True)
        return True

    def _do_clipboard(self, cmd):
        """cmd['value'] 写进剪切板；空串合法（= 清空）。"""
        text = cmd.get('value')
        if not isinstance(text, str):
            print('[Desktop] 剪切板指令缺 value（需字符串）: %s' % cmd, flush=True)
            return False
        if not set_clipboard_text(text):
            return False
        print('[Desktop] 剪切板已写入 %d 字: %s'
              % (len(text), text[:60]), flush=True)
        return True

    def _report_done(self, cmd):
        """执行成功才发：{'queue': …, 'type': 'done', 'command': <原指令>, 'time': …}。"""
        meta = {
            'queue': QUEUE_DESKTOP_SUB,
            'type': 'done',
            'command': cmd,
            'time': time.strftime('%Y-%m-%d %H:%M:%S'),
        }
        self.queues[QUEUE_DESKTOP_SUB].put(meta)
        print('[Desktop] 指令完成已入队 %s: %s' % (QUEUE_DESKTOP_SUB, cmd),
              flush=True)
