"""MainLoop 全链路 PC 冒烟测试：假 machine(I2S) + 假 broker。

跑法（在 esp32_client/ 目录下）：
    python tests/smoke_loop.py

验证（不需要真实 ESP32 / broker）：
  1. MainLoop.run() 启动 → 连接 → 订阅 pub/ear + pub/speak
  2. EarWorker：假麦克风不断产出 640B 块 → sub/ear 队列 → 发送任务 → broker
  3. SpeakWorker：broker 下行 pub/speak(2000B) → I2S 桩分块写入总长正确
  4. MainLoop.stop()：哨兵停机、任务清空、两个 I2S 均 deinit
"""
import asyncio
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

# 现在才允许 import（workers 顶层 import machine）
from src.main_loop import MainLoop  # noqa: E402
from tests.smoke_mqtt import FakeBroker  # noqa: E402

from src.mqtt import _encode_str, _encode_varint  # noqa: E402
from src import config  # noqa: E402


async def wait_until(pred, timeout=6.0, what='condition'):
    deadline = asyncio.get_event_loop().time() + timeout
    while not pred():
        if asyncio.get_event_loop().time() > deadline:
            raise AssertionError(f'timeout waiting: {what}')
        await asyncio.sleep(0.02)


async def main():
    broker = FakeBroker()
    server = await asyncio.start_server(broker.handler, '127.0.0.1', 0)
    port = server.sockets[0].getsockname()[1]

    loop = MainLoop(broker='127.0.0.1', port=port)
    run_task = asyncio.create_task(loop.run())

    try:
        # ---- 1) 连接 + 订阅 ----
        await wait_until(lambda: loop.mqtt.connected, what='mqtt connected')
        await wait_until(lambda: broker.subscribes >= 2, what='subscribe x2')
        assert len(loop._tasks) == 4, len(loop._tasks)   # 引擎+发送+ear+speak

        # ---- 2) EarWorker：上行音频不断到达 broker ----
        await wait_until(lambda: len(broker.rx_pub) >= 3,
                         what='broker 收到 >=3 条上行')
        assert {t for t, _ in broker.rx_pub} == {'sub/ear'}
        assert all(len(p) == config.MIC_CHUNK for _, p in broker.rx_pub), \
            [len(p) for _, p in broker.rx_pub[:3]]

        # ---- 3) SpeakWorker：下行 2000B 全部写进 I2S 桩 ----
        payload = b'\xAB' * 2000
        w = broker.conn_writers[-1]
        body = _encode_str('pub/speak') + payload
        w.write(b'\x30' + _encode_varint(len(body)) + body)
        await w.drain()

        await wait_until(
            lambda: sum(len(i.written) for i in _i2s_registry) >= 2000,
            what='speak 写入 2000B')

        # ---- 4) 停机 ----
        await loop.stop()
        assert loop._tasks == [], loop._tasks
        await asyncio.wait_for(run_task, 3)
        assert all(i.deinited for i in _i2s_registry), 'I2S 未全部 deinit'

        total = sum(len(i.written) for i in _i2s_registry)
        print(f'SMOKE LOOP PASS: rx_pub={len(broker.rx_pub)}条, '
              f'speak 写入 {total}B, I2S 均 deinit')
    finally:
        server.close()
        await server.wait_closed()


if __name__ == '__main__':
    asyncio.run(main())
