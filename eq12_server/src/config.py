

BROKER = "192.168.0.108"   # local Mosquitto broker
PORT = 1883            # default MQTT port

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