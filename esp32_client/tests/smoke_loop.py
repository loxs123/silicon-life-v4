"""MainLoop 全链路 PC 冒烟测试：假 machine(I2S) + 假 camera/jpeg + 假 broker。

跑法（在 esp32_client/ 目录下）：
    python tests/smoke_loop.py

验证（不需要真实 ESP32 / broker / 摄像头 / 舵机电机 / 屏）：
  1. MainLoop.run() 启动 → 连接 → 订阅 pub/ear + pub/speak + pub/eye
     + pub/leg + pub/face
  2. EarWorker：假麦克风不断产出 640B 块 → sub/ear 队列 → 发送任务 → broker
  3. CameraWorker：broker 下行 pub/eye(b'photo') → 假相机拍帧 → 假 jpeg 编码
     → sub/eye 队列出现 JSON 信封（base64 data 与"编码结果"一致）
  4. MoveWorker（假 PCA9685）：pub/leg 指令串行执行——pan/tilt 限幅就位、
     forward 跑 0.2s 后自动停、center 复位、错误载荷不触发；
     每条真做完的指令上行一条 done 回执到 sub/leg（电机跑完自动停之后才发）
  5. ScreenWorker（假 Face）：pub/face 表情指令按序切换——[SCR]: 前缀、
     neutral 别名、未知表情跳过
  6. SpeakWorker：broker 下行 pub/speak(2000B) → I2S 桩分块写入总长正确
  7. MainLoop.stop()：哨兵停机、任务清空、所有 I2S 均 deinit
"""
import asyncio
import binascii
import json
import os
import sys
import types

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# ------------------------------------------------- 假 machine（在 import 前装好）
_machine = types.ModuleType('machine')
_i2s_registry = []


class _Pin:
    def __init__(self, n):
        self.n = n


class _I2S:
    RX = 0
    TX = 1
    MONO = 0

    def __init__(self, i2s_id, **kw):
        self.id = i2s_id
        self.mode = kw.get('mode')
        self.deinited = False
        self.written = bytearray()
        self._seq = 0
        _i2s_registry.append(self)

    def readinto(self, buf):
        """假麦克风：立即填满一块（内容 = 递增的相同字节），不阻塞。"""
        self._seq = (self._seq + 1) % 256
        buf[:] = bytes([self._seq]) * len(buf)
        return len(buf)

    def write(self, data):
        self.written += data
        return len(data)

    def deinit(self):
        self.deinited = True


_machine.Pin = _Pin
_machine.I2S = _I2S
sys.modules['machine'] = _machine

# --------------------------- 假 camera / jpeg 固件模块（延迟 import，跑前注入）
# CameraWorker 在方法内才 from camera import ... / import jpeg，
# 因此这里塞进 sys.modules 即可让 PC 上跑通整条拍照链路。
FAKE_JPEG = b'\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01FAKE-PHOTO\xff\xd9'
_fake_cam = types.ModuleType('camera')


class _FakeCamera:
    def __init__(self, **kw):
        self.kw = kw
        self.deinited = False

    def get_sensor_name(self):
        return 'OV3660-fake'

    def capture(self):
        """假帧：QVGA RGB565 全零（153600B），内容无所谓，jpeg 桩不读它。"""
        return bytearray(320 * 240 * 2)

    def deinit(self):
        self.deinited = True


_fake_cam.Camera = _FakeCamera
_fake_cam.PixelFormat = types.SimpleNamespace(RGB565=0)
_fake_cam.FrameSize = types.SimpleNamespace(QVGA=0, VGA=0, SVGA=0)
sys.modules['camera'] = _fake_cam

_fake_jpeg = types.ModuleType('jpeg')


class _FakeEncoder:
    def __init__(self, **kw):
        self.kw = kw

    def encode(self, frame):
        return FAKE_JPEG


_fake_jpeg.Encoder = _FakeEncoder
sys.modules['jpeg'] = _fake_jpeg

# 现在才允许 import（workers 顶层 import machine）
from src.main_loop import MainLoop, _Queue, _Msg, _STOP  # noqa: E402
from src.workers import MoveWorker, ScreenWorker  # noqa: E402
from tests.smoke_mqtt import FakeBroker  # noqa: E402

from src.mqtt import _encode_str, _encode_varint  # noqa: E402
from src import config  # noqa: E402


async def wait_until(pred, timeout=6.0, what='condition'):
    deadline = asyncio.get_event_loop().time() + timeout
    while not pred():
        if asyncio.get_event_loop().time() > deadline:
            raise AssertionError(f'timeout waiting: {what}')
        await asyncio.sleep(0.02)


# ------------------------------------------------- 假 PCA9685（MoveWorker 直测用）
class FakePwm:
    def __init__(self):
        self.duties = []    # (channel, value)
        self.angles = []    # (channel, angle)

    def duty(self, ch, v):
        self.duties.append((ch, v))

    def servo_angle(self, ch, a):
        self.angles.append((ch, int(a)))

    def set_freq(self, f):
        pass


# ------------------------------------------------- 假 Face（ScreenWorker 直测用）
class FakeFace:
    def __init__(self):
        self.ok = True
        self.states = []

    def set_state(self, s):
        self.states.append(s)

    async def run(self):
        return          # 无动画，立即结束


async def main():
    broker = FakeBroker()
    server = await asyncio.start_server(broker.handler, '127.0.0.1', 0)
    port = server.sockets[0].getsockname()[1]

    loop = MainLoop(broker='127.0.0.1', port=port)
    run_task = asyncio.create_task(loop.run())

    try:
        # ---- 1) 连接 + 订阅 ----
        await wait_until(lambda: loop.mqtt.connected, what='mqtt connected')
        await wait_until(lambda: broker.subscribes >= 5, what='subscribe x5')
        # 引擎 + 3 个上行发送任务(sub/ear, sub/eye, sub/leg)
        #     + ear + speak + camera + move + screen = 9
        assert len(loop._tasks) == 9, len(loop._tasks)

        # ---- 2) EarWorker：上行音频不断到达 broker ----
        await wait_until(lambda: len(broker.rx_pub) >= 3,
                         what='broker 收到 >=3 条上行')
        assert {t for t, _ in broker.rx_pub} == {'sub/ear'}
        assert all(len(p) == config.MIC_CHUNK for _, p in broker.rx_pub), \
            [len(p) for _, p in broker.rx_pub[:3]]

        # ---- 3) CameraWorker：pub/eye 拍照指令 → 一张照片上行 sub/eye ----
        n_before = len(broker.rx_pub)
        w = broker.conn_writers[-1]
        body = _encode_str('pub/eye') + b'photo'
        w.write(b'\x30' + _encode_varint(len(body)) + body)
        await w.drain()

        await wait_until(
            lambda: any(t == 'sub/eye' for t, _ in broker.rx_pub[n_before:]),
            timeout=8, what='broker 收到 sub/eye 照片')

        photo_msgs = [(t, p) for t, p in broker.rx_pub[n_before:]
                      if t == 'sub/eye']
        assert len(photo_msgs) == 1, len(photo_msgs)
        env = json.loads(photo_msgs[0][1].decode('utf-8'))
        assert env['type'] == 'photo' and env['size'] == len(FAKE_JPEG)
        assert env['width'] == 320 and env['height'] == 240
        assert binascii.a2b_base64(env['data']) == FAKE_JPEG

        # 拍照指令的载荷必须严格等于 b'photo'：乱发载荷不该触发拍照
        # （耳麦仍在持续上行 sub/ear，所以只看这段区间里有没有 sub/eye）
        n_before = len(broker.rx_pub)
        body = _encode_str('pub/eye') + b'bogus'
        w.write(b'\x30' + _encode_varint(len(body)) + body)
        await w.drain()
        await asyncio.sleep(0.3)
        assert not [t for t, _ in broker.rx_pub[n_before:]
                    if t == 'sub/eye'], '错误载荷不应触发拍照'

        # ---- 4) SpeakWorker：下行 2000B 全部写进 I2S 桩 ----
        payload = b'\xAB' * 2000
        w = broker.conn_writers[-1]
        body = _encode_str('pub/speak') + payload
        w.write(b'\x30' + _encode_varint(len(body)) + body)
        await w.drain()

        await wait_until(
            lambda: sum(len(i.written) for i in _i2s_registry) >= 2000,
            what='speak 写入 2000B')

        # ---- 5) 停机 ----
        await loop.stop()
        assert loop._tasks == [], loop._tasks
        await asyncio.wait_for(run_task, 3)
        assert all(i.deinited for i in _i2s_registry), 'I2S 未全部 deinit'

        # ---- 6) MoveWorker：pub/leg 串行执行 + 完成回执上行 sub/leg ----
        fpwm = FakePwm()
        mv_queues = {'pub/leg': _Queue(), 'sub/leg': _Queue()}
        mv = MoveWorker(mv_queues, stop_token=_STOP, pca9685=fpwm)
        mv_task = asyncio.create_task(mv.run())

        async def leg_cmd(text):
            mv_queues['pub/leg'].put_nowait(_Msg('pub/leg', text.encode('utf-8')))

        async def next_done():
            """取 worker 发到 sub/leg 的下一条完成回执（没有就等，2s 超时）。"""
            item = await asyncio.wait_for(mv_queues['sub/leg'].get(), 2)
            if isinstance(item, (bytes, bytearray)):
                return item.decode('utf-8')
            return str(item)

        await asyncio.sleep(0.02)        # worker 起跑（pwm 已注入，跳过 _init_pwm）

        await leg_cmd('pan,200')         # 越界 → 钳到 pan_max=120
        await leg_cmd('[MOVE]:tilt,60')  # 兼容旧前缀
        assert await next_done() == 'done:pan,200'
        assert await next_done() == 'done:tilt,60'   # 规范化回执（去前缀）
        assert fpwm.angles == [(0, 120), (1, 60)], fpwm.angles

        await leg_cmd('forward,50,0.2')  # 电机跑 0.2s（之后自动停）
        await asyncio.sleep(0.1)
        assert any(v > 0 for _, v in fpwm.duties), fpwm.duties[-6:]
        assert await next_done() == 'done:forward,50,0.2'  # 跑完自动停才回执
        await asyncio.sleep(0.25)        # 超过 0.2s → 自动停：四通道最后写 0
        assert all(v == 0 for _, v in fpwm.duties[-4:]), fpwm.duties[-4:]

        await leg_cmd('right,30,0.1')    # 串行：跑完才执行后面的 center
        await leg_cmd('center')
        assert await next_done() == 'done:right,30,0.1'
        assert await next_done() == 'done:center'
        assert (0, 90) in fpwm.angles and (1, 90) in fpwm.angles

        await leg_cmd('bogus')           # 未知指令：不执行也不回执
        await asyncio.sleep(0.05)
        assert mv_queues['sub/leg'].qsize() == 0

        mv_queues['pub/leg'].put_nowait(_STOP)
        await asyncio.wait_for(mv_task, 2)
        assert mv_queues['sub/leg'].qsize() == 0

        # ---- 7) ScreenWorker：pub/face 表情指令按序切换（假 Face）----
        fface = FakeFace()
        sf_queues = {'pub/face': _Queue()}
        sw = ScreenWorker(sf_queues, stop_token=_STOP, face=fface)
        sw_task = asyncio.create_task(sw.run())

        async def face_cmd(text):
            sf_queues['pub/face'].put_nowait(_Msg('pub/face', text.encode('utf-8')))

        await asyncio.sleep(0.02)        # worker 起跑（face 已注入，跳过 _init_face）
        await face_cmd('[SCR]:happy')    # 兼容旧前缀
        await face_cmd('neutral')        # 别名 → idle
        await face_cmd(' SLEEP ')        # 大小写/空格容错 → sleep
        await face_cmd('bogus')          # 未知表情：跳过，不改状态
        await asyncio.sleep(0.2)
        assert fface.states == ['happy', 'idle', 'sleep'], fface.states

        sf_queues['pub/face'].put_nowait(_STOP)
        await asyncio.wait_for(sw_task, 2)
        print(f'SMOKE LOOP PASS: rx_pub={len(broker.rx_pub)}条'
              f'(含照片{len([t for t, _ in broker.rx_pub if t == "sub/eye"])}张), '
              f'speak 写入 {sum(len(i.written) for i in _i2s_registry)}B, '
              f'move 动作 {len(fpwm.angles)} 次, face 表情 {len(fface.states)} 个, '
              f'I2S 均 deinit')
    finally:
        server.close()
        await server.wait_closed()


if __name__ == '__main__':
    asyncio.run(main())
