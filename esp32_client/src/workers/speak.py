"""嘴器官（esp32 端）：订阅 pub/speak（下行 TTS 语音流）→ I2S 播放。

与 eq12_server 的对应关系：
    eq12_server 的 SpeakWorker 把 TTS 语音发布到 pub/speak；
    本 worker 是它的"下游半身"——收到下行裸 PCM 音频逐块喂喇叭。

播放要点（经验来自 v3 的 src/actors/speaker.py，ESP32 实测）：
  * 写块粒度 ~31ms（config.SPK_CHUNK），块太小写调用过密反而卡/刺啦；
  * DMA 起播预热：每段播放开始时 DMA 缓冲是空的，若从第一块起就边写边
    让出，调度一忙就欠载 → 开头"卡卡/刺啦"。冷启动先一次性灌入约 0.3s
    音频（写满 DMA 空缓冲几乎不阻塞），再逐块写 + sleep(0) 让出；
  * 块间用 sleep(0) 纯让出事件循环，不用 sleep(ms) 制造人工间隙。
音量衰减在 EQ12 端做（speak_worker 的 VOLUME_DIV），这里只裸播。
"""
try:
    import asyncio
except ImportError:
    import uasyncio as asyncio

import machine

from .. import config

DMA_WARM_BYTES = 15360      # 起播预热量 ≈ 0.32s @ 24k（约等于 ibuf 16384，参考 v3）


class SpeakWorker:
    def __init__(self, queues, stop_token=None, echo=None):
        self.queues = queues
        self.stop_token = stop_token
        self.echo = echo               # 共享回声闸；播完刷新活动时间
        self._cold = True              # 下一段是"冷启动"（DMA 空）→ 需预热

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
        print('[speak] 已启动（音量在 EQ12 端控制）')
        try:
            while True:
                msg = await self.queues['pub/speak'].get()
                if self.stop_token is not None and msg is self.stop_token:
                    break
                data = msg.payload
                off = 0

                # 1) 冷启动预热：空 DMA 一次性灌 ~0.3s，防起播欠载爆音
                if self._cold and data:
                    pre = data[:DMA_WARM_BYTES]
                    try:
                        self.i2s.write(pre)
                        off = len(pre)
                    except OSError:
                        off = 0              # 失败就退回正常逐块写
                    self._cold = False

                # 2) 逐块写（~31ms/块），每块写完让出事件循环
                while off < len(data):
                    try:
                        self.i2s.write(data[off:off + config.SPK_CHUNK])
                    except OSError:
                        break                # 喇叭异常：丢这一整块
                    off += config.SPK_CHUNK
                    await asyncio.sleep(0)   # 纯让出，不制造人工间隙

                # 3) 队列已空 → 下一条消息按冷启动处理（预热一次）
                if self.queues['pub/speak'].qsize() == 0:
                    self._cold = True
                if self.echo is not None:
                    self.echo.mark_played()  # 播完：ear 据此延后恢复上行
        finally:
            self.i2s.deinit()
