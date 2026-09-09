"""嘴器官（esp32 端）：订阅 pub/speak（下行 TTS 语音流）→ I2S 播放。

与 eq12_server 的对应关系：
    eq12_server 的 SpeakWorker 把 TTS 语音发布到 pub/speak；
    本 worker 是它的"下游半身"——收到下行裸 PCM 音频逐块喂喇叭。
    采样率/位深/声道与 config.SPK_RATE 约定一致（24k/16bit/mono，见 config.py
    注释：下行 TTS 是 24kHz，与上行 ASR 的 16kHz 不同）。
"""
try:
    import asyncio
except ImportError:
    import uasyncio as asyncio

import machine

from .. import config


class SpeakWorker:
    def __init__(self, queues, stop_token=None, echo=None):
        self.queues = queues
        self.stop_token = stop_token
        self.echo = echo               # 共享回声闸；收到音频时刷新活动时间

        spk = config.SPK
        self.i2s = machine.I2S(
            spk['id'],
            sck=machine.Pin(spk['sck']),
            ws=machine.Pin(spk['ws']),
            sd=machine.Pin(spk['sd']),
            mode=machine.I2S.TX,
            bits=16,
            format=machine.I2S.MONO,
            rate=config.SPK_RATE,
            ibuf=config.I2S_IBUF,
        )

    async def run(self):
        # 消费者型 worker：get() 阻塞等待，与 eq12 的 worker 循环完全同构
        print('[speak] 已启动')
        try:
            while True:
                msg = await self.queues['pub/speak'].get()
                if self.stop_token is not None and msg is self.stop_token:
                    break
                data = msg.payload
                # 下行块可能很大，拆成 config.SPK_CHUNK 小块喂 I2S，
                # 块间让出调度，避免长时间占死事件循环
                for off in range(0, len(data), config.SPK_CHUNK):
                    try:
                        self.i2s.write(data[off:off + config.SPK_CHUNK])
                    except OSError:
                        break               # 喇叭异常：丢这一整块
                    await asyncio.sleep(0.001)
                if self.echo is not None:
                    # 这一条播完了：ear 据此在"队列空 + 静默够久"后才恢复上行
                    self.echo.mark_played()
        finally:
            self.i2s.deinit()
