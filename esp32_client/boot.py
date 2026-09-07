"""esp32 开机引导：只负责联网，连不上就一直重试，绝不往下走。

main.py 里默认 WiFi 已就绪；运行中 WiFi 掉线的重连逻辑不在本文件范围内
（最小实现：MQTT 引擎会重试，但若 WiFi 本身断了需另加检测）。
"""
import network
import time

WIFI_SSID = "your_wifi"
WIFI_PASS = "your_password"

wlan = network.WLAN(network.STA_IF)
wlan.active(True)

while not wlan.isconnected():
    print("wifi connecting...")
    try:
        wlan.connect(WIFI_SSID, WIFI_PASS)
    except OSError as e:
        print("connect err:", e)
    for _ in range(50):               # 每次尝试等 ~10s
        if wlan.isconnected():
            break
        time.sleep(0.2)

print("wifi ok:", wlan.ifconfig()[0])
