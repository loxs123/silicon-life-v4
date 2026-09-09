# -*- coding: utf-8 -*-
"""脸器官（esp32 端）：1.54" ST7789 表情屏，pub/face 指令切换表情。

与 eq12_server 的对应关系：
    eq12 的 BrainWorker（或其它角色）下发表情指令 pub/face（下行，载荷为文本
    UTF-8），本 worker 收到一条切一个表情，**一条画完才取下一条**（切表情 = 整脸
    重画推屏，是同步动作，队列里排着就按序一张一张来）。

指令载荷（格式与 v3 src/actors/screen.py 完全一致，可带 "[SCR]:" 前缀）：
    idle     待机（微笑）      listen  聆听（眼睛下移 O 嘴）
    think    思考（眼球上瞟）  speak   说话（嘴部开合动画）
    happy    开心（咧嘴）      sleep   睡觉（闭眼 zzz）
    兼容别名 neutral → idle；大小写不敏感、可带空格。

表情特性：
    自带**眨眼动画**（每 2~4s 一次，只在 idle/listen/think/happy 等睁眼状态眨）；
    speak 状态由动画任务持续做嘴部开合（局部推屏），直到收到下一条指令切走。

与其它器官的约定一致：所有屏参数（分辨率/SPI/引脚/帧方向）在 src/config.py 的
SCREEN；颜色/画法在下面代码里（属于"画什么"，不是接线参数）。
⚠️ 接线/踩坑见 docs/引脚分配与接线.md「1.54 寸屏 ST7789」节：必须 SPI(1)；
   GPIO43/44 占 TTL 口 → 跑屏时别插 TTL 线（烧录/REPL 走 OTG）。
"""
try:
    import asyncio
except ImportError:
    import uasyncio as asyncio

import time

from .. import config

# ticks_ms/ticks_diff 是 MicroPython API；CPython（PC 冒烟测试）没有，用 monotonic 兜底
try:
    _ticks_ms = time.ticks_ms
    _ticks_diff = time.ticks_diff
except AttributeError:
    _ticks_ms = lambda: int(time.monotonic() * 1000)
    _ticks_diff = lambda a, b: a - b

_SC = config.SCREEN


def _create_task(coro):
    """跨平台创建任务：MicroPython 裁剪固件可能缺 ensure_future"""
    if hasattr(asyncio, 'create_task'):
        return asyncio.create_task(coro)
    if hasattr(asyncio, 'ensure_future'):
        return asyncio.ensure_future(coro)
    return asyncio.get_event_loop().create_task(coro)


# ============ 颜色（framebuf RGB565，小端 → 面板大端交换字节）============

def _rgb(c):
    v = ((c[0] & 0xF8) << 8) | ((c[1] & 0xFC) << 3) | (c[2] >> 3)
    return ((v & 0xFF) << 8) | (v >> 8)   # 交换字节（framebuf 小端 → 面板大端）


BG = _rgb((22, 24, 32))      # 深色背景
RING = _rgb((240, 170, 40))  # 脸描边（橙）
FACE = _rgb((255, 205, 70))  # 肤色（黄）
EYE = _rgb((60, 50, 45))     # 眼睛（深棕）
HI = _rgb((255, 255, 255))   # 高光
CHEEK = _rgb((255, 145, 140))  # 腮红
MOUTH = _rgb((90, 60, 50))   # 嘴（深棕）


# ==================================================================
# ST7789 最小驱动（240x240 RGB565，来自 v3 screen_demo.py / face.py）
# ==================================================================

class ST7789:
    def __init__(self, spi, dc, cs):
        self.spi, self.dc, self.cs = spi, dc, cs
        self.w, self.h = _SC['w'], _SC['h']
        self._init(_SC['madctl'])

    def _cmd(self, c):
        self.cs(0); self.dc(0); self.spi.write(bytes([c])); self.cs(1)

    def _data(self, d):
        self.cs(0); self.dc(1); self.spi.write(d); self.cs(1)

    def _init(self, madctl):
        seq = [(0x01, None, 150), (0x11, None, 150), (0x3A, b'\x55', 10),
               (0x36, bytes([madctl]), 10), (0x21, None, 10), (0x13, None, 10),
               (0x29, None, 50)]
        for c, d, ms in seq:
            self._cmd(c)
            if d:
                self._data(d)
            time.sleep_ms(ms)

    def blit_rect(self, buf, x0, y0, x1, y1):
        """把 buf 中 (x0,y0)-(x1,y1) 区域推给屏幕（逐行分块写，颜色字节已就绪）"""
        self._cmd(0x2A)
        self._data(bytes([x0 >> 8, x0 & 0xFF, x1 >> 8, x1 & 0xFF]))
        self._cmd(0x2B)
        self._data(bytes([y0 >> 8, y0 & 0xFF, y1 >> 8, y1 & 0xFF]))
        self._cmd(0x2C)
        w = x1 - x0 + 1
        h = y1 - y0 + 1
        stride = w * 2
        mv = memoryview(buf)
        row_bytes = self.w * 2
        start = y0 * row_bytes + x0 * 2
        self.cs(0); self.dc(1)
        for yy in range(h):
            off = start + yy * row_bytes
            line = mv[off:off + stride]
            for i in range(0, stride, _SC['chunk']):
                self.spi.write(line[i:i + _SC['chunk']])
        self.cs(1)


# ==================================================================
# 表情管理：状态 → 画脸 → 推屏（init 失败 ok=False，不影响机器人）
# ==================================================================

class Face:
    """表情：framebuf 整脸重画 + 整屏/局部推屏；眨眼与说话嘴动画由 run() 驱动。"""

    def __init__(self):
        self.w, self.h = _SC['w'], _SC['h']
        self.cx, self.cy = self.w // 2, self.h // 2
        self.ok = False
        self.state = "idle"
        self._fb = None
        self._tft = None
        self._buf = None
        try:
            from machine import Pin, SPI
            import framebuf
            spi = SPI(_SC['spi_id'], baudrate=_SC['spi_hz'],
                      sck=Pin(_SC['sck']), mosi=Pin(_SC['mosi']))
            self._tft = ST7789(spi, Pin(_SC['dc'], Pin.OUT), Pin(_SC['cs'], Pin.OUT))
            self._buf = bytearray(self.w * self.h * 2)
            self._fb = framebuf.FrameBuffer(self._buf, self.w, self.h,
                                            framebuf.RGB565)
            self.ok = True
            self._redraw()
        except Exception:
            self.ok = False

    # ---------- 状态切换 ----------
    def set_state(self, state):
        if not self.ok or state == self.state:
            return
        self.state = state
        self._redraw()

    # ---------- 眨眼 / 说话动画 ----------
    async def run(self):
        if not self.ok:
            return
        blink_at = _ticks_ms() + 2500
        while True:
            await asyncio.sleep(0.12)
            if not self.ok:
                return
            now = _ticks_ms()
            if self.state == "speak":
                # 说话：嘴部开合动画（只推嘴部区域，省 SPI 流量）
                mouth_h = 6 + (now // 150) % 3 * 5
                self._draw(pupil=(0, 0), mouth="open", mouth_h=mouth_h)
                self._push_rect(self.cx - 34, self.cy + 24,
                                self.cx + 34, self.cy + 108)
            elif _ticks_diff(now, blink_at) > 0:
                self._draw_blink(closed=True)
                await asyncio.sleep(0.14)
                self._draw_blink(closed=False)
                blink_at = now + 2200 + (now % 1800)

    # ---------- 画图 ----------
    def _redraw(self):
        """按当前状态画一整张脸"""
        s = self.state
        if s == "listen":
            pupil, mouth, mh = (0, -4), "o", 8
        elif s == "think":
            pupil, mouth, mh = (-6, -6), "neutral", 0
        elif s == "speak":
            pupil, mouth, mh = (0, 0), "open", 12
        elif s == "happy":
            pupil, mouth, mh = (0, -2), "smile", 0
        elif s == "sleep":
            pupil, mouth, mh = (0, 0), "neutral", 0
        else:  # idle
            pupil, mouth, mh = (0, 0), "smile", 0
        self._draw(pupil=pupil, mouth=mouth, mouth_h=mh,
                   eye_open=(s != "sleep"))
        self._push_face()

    def _draw_blink(self, closed):
        """眨眼：整脸重画（framebuf 快），只推眼睛区域（局部刷新）"""
        if self.state == "sleep":
            return
        self._draw(pupil=(0, 0), mouth="smile", mouth_h=0,
                   eye_open=not closed)
        self._push_rect(self.cx - 74, self.cy - 58,
                        self.cx + 74, self.cy - 10)

    def _draw(self, pupil=(0, 0), mouth="smile", mouth_h=8, eye_open=True):
        """在 framebuf 上整脸重画（大脸布局，几乎铺满 240x240）"""
        fb = self._fb
        cx, cy = self.cx, self.cy
        fb.fill(BG)
        # 脸（铺满）
        fb.ellipse(cx, cy, 118, 118, RING, True)
        fb.ellipse(cx, cy, 114, 114, FACE, True)
        # 腮红
        fb.ellipse(cx - 68, cy + 52, 15, 15, CHEEK, True)
        fb.ellipse(cx + 68, cy + 52, 15, 15, CHEEK, True)
        # 眼睛
        for ex in (cx - 52, cx + 52):
            px, py = ex + pupil[0], cy - 34 + pupil[1]
            if eye_open:
                fb.ellipse(px, py, 19, 20, EYE, True)
                fb.ellipse(px - 6, py - 7, 6, 6, HI, True)
            else:
                fb.rect(px - 19, py - 3, 38, 8, EYE, True)
        # 嘴
        my = cy + 58
        if mouth == "smile":
            fb.ellipse(cx, my, 44, 40, MOUTH, True)
            fb.ellipse(cx, my - 26, 44, 36, FACE, True)
        elif mouth == "open":
            fb.ellipse(cx, my, 26, 12 + mouth_h, MOUTH, True)
        elif mouth == "o":
            fb.ellipse(cx, my - 8, 12, 12, MOUTH, True)
        else:  # neutral
            fb.rect(cx - 22, my - 5, 44, 8, MOUTH, True)
        # 状态小字（右下角）
        label = {"idle": "", "listen": "听", "think": "想", "speak": "说",
                 "happy": "哈", "sleep": "zzz"}.get(self.state, "")
        if label:
            fb.rect(cx - 28, cy + 104, 56, 20, BG, True)
            fb.text(label, cx - 8, cy + 107, EYE)

    def _push_face(self):
        if self._tft:
            # 整屏刷新（含背景边缘），避免四周残留
            self._tft.blit_rect(self._buf, 0, 0, self.w - 1, self.h - 1)

    def _push_rect(self, x0, y0, x1, y1):
        if self._tft:
            self._tft.blit_rect(self._buf, x0, y0, x1, y1)


# ==================================================================
# 脸 worker（actor 包装）
# ==================================================================

class ScreenWorker:
    """脸：pub/face 收表情指令 → 切表情（整脸重画推屏），一条画完才取下一条。

    消费者型 worker（同 speak/camera/move）；表情动画（眨眼/说话嘴）由 Face.run()
    后台协程驱动，与收指令互不阻塞。屏初始化失败/未接线时优雅降级：忽略指令，
    不拖垮其它器官（此时机器人只是"没表情"）。
    """

    STATES = ('idle', 'listen', 'think', 'speak', 'happy', 'sleep')
    ALIAS = {'neutral': 'idle'}

    def __init__(self, queues, stop_token=None, face=None):
        self.queues = queues
        self.stop_token = stop_token
        self.face = face          # 可注入（PC 冒烟/模拟用）；None=设备上自建

    async def _init_face(self):
        """初始化屏幕 + 表情（失败优雅降级，保持存活）"""
        try:
            f = Face()
            self.face = f if f.ok else None
            if self.face is None:
                print('[face] 屏初始化失败（跳过表情，检查接线/供电/SPI(1)）')
            else:
                print('[face] 屏幕就绪 (%dx%d)' % (f.w, f.h))
        except Exception as e:
            print('[face] 屏幕初始化异常: %s' % e)
            self.face = None

    @staticmethod
    def _parse(msg):
        """解析表情名（支持 "[SCR]:speak" / "speak" / " SPEAK "，返回小写名或 None）"""
        if isinstance(msg, bytes):
            text = msg.decode('utf-8', 'ignore')
        else:
            text = str(msg)
        text = text.strip()
        if text.startswith('[SCR]:'):
            text = text[len('[SCR]:'):].strip()
        return text.lower() or None

    async def run(self):
        print('[face] 脸就绪：pub/face 指令切换表情（%s）' % '/'.join(self.STATES))
        if self.face is None:
            await self._init_face()

        # 后台动画：眨眼 / 说话嘴部开合（仅在屏可用时）
        anim = None
        if self.face is not None and self.face.ok:
            anim = _create_task(self.face.run())
        try:
            while True:
                msg = await self.queues['pub/face'].get()
                if self.stop_token is not None and msg is self.stop_token:
                    break
                state = self._parse(msg.payload)
                if state is None:
                    continue
                state = self.ALIAS.get(state, state)
                if state not in self.STATES:
                    print('[face] 未知表情: %s（可选 %s）'
                          % (state, '/'.join(self.STATES)))
                    continue
                if self.face is not None:
                    self.face.set_state(state)   # 同步重画推屏：画完才取下一条
                    print('[face] 表情: %s' % state)
                else:
                    print('[face] 屏幕未就绪，忽略表情: %s' % state)
        finally:
            if anim is not None:
                anim.cancel()
