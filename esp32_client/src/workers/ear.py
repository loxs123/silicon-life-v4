"""耳朵器官（esp32 端）：I2S 麦克风 → 上行 sub/ear 出站队列。

与 eq12_server 的对应关系：
    eq12_server 的 EarWorker 消费 sub/ear（收到器官音频）送 ASR；
    本 worker 是它的"上游半身"——把麦克风采样的裸 PCM 持续放入出站队列
    sub/ear（由主循环的专职发送任务发布到 broker，EQ12 订阅后做 ASR）。

采集启停受下行 pub/ear 指令控制（载荷 b'start' / b'stop'）。
生产型 worker：不阻塞在入站 get() 上，优雅停机靠 MainLoop.stop() 超时取消。
"""
try:
    import asyncio
except ImportError:
    import uasyncio as asyncio

import machine

from .. import config


class EarWorker:
    def __init__(self, queues, stop_token=None):
        self.queues = queues
        self.stop_token = stop_token
        self._enabled = True
        self._buf = bytearray(config.CHUNK)

        mic = config.MIC
        self.i2s = machine.I2S(
            mic['id'],
            sck=machine.Pin(mic['sck']),
            ws=machine.Pin(mic['ws']),
            sd=machine.Pin(mic['sd']),
            mode=machine.I2S.RX,
            bits=16,
            format=machine.I2S.MONO,
            rate=config.RATE,
            ibuf=config.I2S_IBUF,
        )

    async def run(self):
        ctl = asyncio.create_task(self._control())
        try:
            while True:
                try:
                    # 阻塞到 DMA 攒满一块（~20ms）；DMA 缓冲兜底调度抖动
                    self.i2s.readinto(self._buf)
                except OSError:
                    await asyncio.sleep(0.01)   # 麦克风异常时别空转刷错误
                    continue
                if self._enabled:
                    self.queues['sub/ear'].put_nowait(bytes(self._buf))
                await asyncio.sleep(0)          # 让出：别饿死网络/播放任务
        finally:
            ctl.cancel()
            self.i2s.deinit()

    async def _control(self):
        """消费 pub/ear 采集指令：与 eq12 的 worker 同款 get() 循环。"""
        q = self.queues['pub/ear']
        while True:
            msg = await q.get()
            if self.stop_token is not None and msg is self.stop_token:
                break
            if msg.payload == b'start':
                self._enabled = True
            elif msg.payload == b'stop':
                self._enabled = False
