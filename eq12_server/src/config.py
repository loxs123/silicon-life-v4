

BROKER = "127.0.0.1"   # 本机 Mosquitto 2.1.2（Windows 服务 "Mosquitto Broker"，只监听 loopback）
# 想切回 EQ12 那台 broker：把上面改成 "192.168.0.108"（实测同样可用、允许匿名收发）
PORT = 1883            # default MQTT port

USE_MQTT = False        # False = 不连 broker，只跑飞书/桌面这类进程内 worker，调飞书和电脑用

SUB_TOPICS = [
    {
        'name': 'sub/brain',
        'qos': 0,
    }, # 脑子
    {
        'name': 'sub/eye',
        'qos': 0,
    },
    {
        'name': 'sub/ear',
        'qos': 0,
    },
    {
        'name': 'sub/mouth',
        'qos': 0,
    },
    {
        'name': 'sub/leg',
        'qos': 0,
    },
    {
        'name': 'sub/face',
        'qos': 0,
    }
]

PUB_TOPICS = [
    {
        'name': 'pub/brain',
        'qos': 0,
    }, # 脑子
    {
        'name': 'pub/eye',
        'qos': 0,
    },
    {
        'name': 'pub/ear',
        'qos': 0,
    },
    {
        'name': 'pub/mouth',
        'qos': 0,
    },
    {
        'name': 'pub/speak',
        'qos': 0,
    }, # 说话:下行 TTS 语音流(ESP32 订阅播放)
    {
        'name': 'pub/leg',
        'qos': 0,
    },
    {
        'name': 'pub/face',
        'qos': 0,
    }
]