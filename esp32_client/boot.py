# This file is executed on every boot (including wake-boot from deepsleep)

# 连接 WiFi
import network
import time

SSID = "904"
PASSWORD = "17701294987"

wlan = network.WLAN(network.STA_IF)
wlan.active(True)

if not wlan.isconnected():
    print("Connecting to WiFi...")
    wlan = network.WLAN(network.STA_IF)
    wlan.active(True)
    wlan.config(pm=network.WLAN.PM_NONE)     # ← 关闭 WiFi 省电，换低延迟
    wlan.connect(SSID, PASSWORD)
    for _ in range(15):                 # 最多等 15 秒，避免连不上时卡死开机
        if wlan.isconnected():
            break
        time.sleep(1)

if wlan.isconnected():
    print("WiFi connected:", wlan.ifconfig()[0])

    # 同步系统时间（NTP，转北京时区 UTC+8）
    # 不设置的话 RTC 默认 2000-01-01，日志时间戳会是 2000 年
    try:
        import machine
        import ntptime
        ntptime.host = "ntp.aliyun.com"     # 国内 NTP，比默认 pool.ntp.org 稳定
        ntptime.settime()                    # 同步的是 UTC
        t = time.localtime(time.time() + 8 * 3600)   # 转北京时间
        machine.RTC().datetime((t[0], t[1], t[2], t[6], t[3], t[4], t[5], 0))
        print("RTC 已同步: %04d-%02d-%02d %02d:%02d:%02d"
              % (t[0], t[1], t[2], t[3], t[4], t[5]))
    except Exception as e:
        print("时间同步失败:", e)
else:
    print("WiFi TIMEOUT, continue without network")

# WebREPL：开机自启（免 USB 线传文件/调试）
try:
    import webrepl
    webrepl.start()
except Exception as e:
    print("webrepl start failed:", e)
