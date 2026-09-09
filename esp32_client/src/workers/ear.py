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
import time

from .. import config

# ticks_ms/ticks_diff 是 MicroPython API；CPython（PC 冒烟测试）没有，
# 用 monotonic 兜底，让同一份代码两端都能跑。
try:
    _ticks_ms = time.ticks_ms
    _ticks_diff = time.ticks_diff
except AttributeError:
    _ticks_ms = lambda: int(time.monotonic() * 1000)
    _ticks_diff = lambda a, b: a - b


class EarWorker:
    def __init__(self, queues, stop_token=None, echo=None):
        self.queues = queues
        self.stop_token = stop_token
        self.echo = echo               # 共享回声闸（_EchoGate）；None=不启用
        self._enabled = True
        self._buf = bytearray(config.MIC_CHUNK)

        mic = config.MIC
        self.i2s = machine.I2S(
            mic['id'],
            sck=machine.Pin(mic['sck']),
            ws=machine.Pin(mic['ws']),
            sd=machine.Pin(mic['sd']),
            mode=machine.I2S.RX,
            bits=16,
            format=machine.I2S.MONO,
            rate=config.MIC_RATE,
            ibuf=config.I2S_IBUF,
        )

    def _echo_ok(self):
        """回声闸：喇叭已静默够久才允许上行（默认 ECHO_GUARD_MS=400ms）。

        EQ12 在语音"发完"即发 b'start'，但喇叭缓冲尾巴可能还在播；
        若立刻恢复上行会录到自己的声音。这里看 speak 最后一次活动的
        时间戳（由 SpeakWorker 每次收到音频刷新），静默足够才放行。
        """
        if self.echo is None:
            return True
        now = _ticks_ms()
        return _ticks_diff(now, self.echo.last_spk) >= config.ECHO_GUARD_MS

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
                if self._enabled and self._echo_ok():
                    self.queues['sub/ear'].put_nowait(bytes(self._buf))
                await asyncio.sleep(0)          # 让出：别饿死网络/播放任务
        finally:
            ctl.cancel()
            self.i2s.deinit()

    async def _control(self):
        """消费 pub/ear 采集指令（b'stop'/b'start'，回声抑制协议）。

        协议来源：eq12 SpeakWorker 出声前推 b'stop'、句毕推 b'start'（try/finally
        保证任何路径都会恢复）。
        - b'stop'  → 停采。**不**清空 pub/speak 未播缓冲：EQ12 的 TTS 推流往往
          快于实时播放，上一句可能还有几秒音频没播完，清空会把话说"掐断"；
          残余音频在静音期播完即可（麦已停，不会录到自己）。
        - b'start' → 置允许采集；真正恢复上行还要等回声闸（_echo_ok）放行，
          即喇叭静默满 ECHO_GUARD_MS 之后。
        """
        q = self.queues['pub/ear']
        while True:
            msg = await q.get()
            if self.stop_token is not None and msg is self.stop_token:
                break
            if msg.payload == b'stop':
                self._enabled = False
            elif msg.payload == b'start':
                self._enabled = True
