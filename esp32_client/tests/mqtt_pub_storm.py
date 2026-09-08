"""上行压力最小测试 —— 只连续发布 sub/ear，不订阅 pub/*、不碰 I2S/音频。

用途：隔离"持续发布 640B 音频块"本身是否会触发 broker 断连。
与 mqtt_connect_test.py 的区别：那个几乎不发消息；这个以 50 块/秒
（20ms 一块，和真实 EarWorker 同节奏）持续向 sub/ear 发布。

用法（板子已联网，/src 已上传）：
    mpremote connect COM4 run tests/mqtt_pub_storm.py

判定：
    PASS = 连接事件=1（30 秒持续发布从未掉线）→ 发布本身没问题
    FAIL = 掉线循环 → 问题在"持续发布"路径（引擎/broker/网络）
"""
try:
    import asyncio
except ImportError:
    import uasyncio as asyncio

import network
import time
import ubinascii

from src.config import BROKER, PORT, MIC_CHUNK
from src.mqtt import AsyncMQTT

TEST_SECONDS = 30
PERIOD_MS = 20           # 20ms 一块 = 50 块/秒，同真实麦克风节奏
CLIENT_ID = None         # None = MAC 派生唯一 id


def _unique_id():
    mac = network.WLAN(network.STA_IF).config('mac')
    return 'esp32-pub-storm-' + ubinascii.hexlify(mac).decode()[-6:]


async def main():
    wlan = network.WLAN(network.STA_IF)
    if not wlan.isconnected():
        print('WiFi 未连接：请先 reset 跑 boot.py')
        return

    mqtt = AsyncMQTT(CLIENT_ID or _unique_id(), BROKER, PORT,
                     keepalive=30, reconnect_delay=2.0)
    conns = [0]
    sent = [0]
    t0 = time.ticks_ms()

    def on_connect():
        conns[0] += 1
        print('[storm] 第 %d 次连接成功 @ %.1fs' % (
            conns[0], time.ticks_diff(time.ticks_ms(), t0) / 1000))

    mqtt.on_connect = on_connect
    task = asyncio.create_task(mqtt.run())
    try:
        last = [0]
        while time.ticks_diff(time.ticks_ms(), t0) < TEST_SECONDS * 1000:
            await asyncio.sleep(0.005)
            if mqtt.connected:
                now = time.ticks_ms()
                if time.ticks_diff(now, last[0]) >= PERIOD_MS:
                    last[0] = now
                    sent[0] += 1
                    await mqtt.publish('sub/ear', b'\x00' * MIC_CHUNK)
        print('')
        ok = conns[0] == 1
        print('[storm] 汇总: 连接事件=%d, 已发=%d 块, 结果=%s' % (
            conns[0], sent[0], 'PASS' if ok else 'FAIL'))
        print('[storm] PASS = 持续发布从未掉线；FAIL = 发布路径有问题')
    finally:
        task.cancel()
        try:
            await task
        except (Exception, asyncio.CancelledError):
            pass


if __name__ == '__main__':
    asyncio.run(main())
