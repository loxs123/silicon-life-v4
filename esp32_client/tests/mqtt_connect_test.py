"""ESP32 MQTT 连通性最小测试 —— 不碰音频 / I2S / 主循环。

只验证一件事：ESP32 能不能连上 broker 并稳定保持连接。
隔离设计（配合排障）：
  * client_id 用 MAC 派生唯一值 → 排除"同 id 互踢"
  * 不走 MainLoop / 不初始化 I2S → 排除音频硬件干扰
  * 用独立 test/# 主题 → 不污染 sub/ear、pub/speak 业务流量

用法（板子已联网，/src 已上传）：
    mpremote connect COM4 run tests/mqtt_connect_test.py

运行 TEST_SECONDS 秒：每 5s 向 test/hello 发一个计数心跳；
EQ12 上 `mosquitto_sub -t 'test/#' -v` 应能看到心跳；
EQ12 上 `mosquitto_pub -t test/echo -m hello` 可验证下行。

判定：
    PASS = 全程 on_connect 只触发 1 次（从未掉线），心跳正常
    FAIL = 出现断开日志 / on_connect 多次 → broker 或网络问题
"""
try:
    import asyncio
except ImportError:
    import uasyncio as asyncio

import network
import time
import ubinascii

from src.config import BROKER, PORT
from src.mqtt import AsyncMQTT

TEST_SECONDS = 60        # 跑多久
HEARTBEAT = 5            # 每几秒发一次心跳
CLIENT_ID = None         # None = 用 MAC 派生唯一 id；也可写死便于看 broker 日志


def _unique_id():
    mac = network.WLAN(network.STA_IF).config('mac')
    return 'esp32-mqtt-test-' + ubinascii.hexlify(mac).decode()[-6:]


async def _heartbeat(mqtt, t0, beats):
    """每 HEARTBEAT 秒发一次心跳到 test/hello。"""
    while True:
        await asyncio.sleep(HEARTBEAT)
        if mqtt.connected:
            beats[0] += 1
            await mqtt.publish('test/hello', b'beat-%d' % beats[0])
            print('[test] 心跳 #%d @%.0fs' % (
                beats[0], time.ticks_diff(time.ticks_ms(), t0) / 1000))


async def main():
    wlan = network.WLAN(network.STA_IF)
    if not wlan.isconnected():
        print('WiFi 未连接：请先 reset 跑 boot.py，或检查 SSID/密码')
        return

    mqtt = AsyncMQTT(CLIENT_ID or _unique_id(), BROKER, PORT,
                     keepalive=30, reconnect_delay=2.0)
    conns = [0]          # on_connect 触发次数（1 = 从未掉线）
    recvs = [0]
    beats = [0]
    t0 = time.ticks_ms()

    def on_connect():
        conns[0] += 1
        print('[test] 第 %d 次连接成功 @ %.1fs' % (
            conns[0], time.ticks_diff(time.ticks_ms(), t0) / 1000))

    def on_message(topic, payload):
        recvs[0] += 1
        print('[test] 收到 %s: %s' % (topic, payload))

    mqtt.on_connect = on_connect
    mqtt.on_message = on_message
    mqtt.subscribe('test/echo', qos=0)

    task = asyncio.create_task(mqtt.run())
    pump = asyncio.create_task(_heartbeat(mqtt, t0, beats))
    try:
        while time.ticks_diff(time.ticks_ms(), t0) < TEST_SECONDS * 1000:
            await asyncio.sleep(0.5)
        print('')
        ok = conns[0] == 1 and beats[0] >= 3
        print('[test] 汇总: 连接事件=%d, 心跳=%d, 下行=%d, 结果=%s' % (
            conns[0], beats[0], recvs[0], 'PASS' if ok else 'FAIL'))
        print('[test] PASS = 全程只连了一次且心跳正常；FAIL = 掉过线/心跳断')
    finally:
        pump.cancel()
        task.cancel()
        try:
            await task
        except (Exception, asyncio.CancelledError):
            pass


if __name__ == '__main__':
    asyncio.run(main())
