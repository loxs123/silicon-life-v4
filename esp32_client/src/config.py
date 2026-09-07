"""esp32 器官端统一配置 —— 与 eq12_server/src/config.py 同构。

eq12_server 里的 SUB_TOPICS / PUB_TOPICS 是"服务器视角"的订阅/发布：
    服务器订阅 sub/*（器官上行数据）→ 所以器官要**发布** sub/*
    服务器发布 pub/*（器官下行指令）→ 所以器官要**订阅** pub/*
因此本文件沿用同样的变量名，内容却是"器官端动作"，语义不变：
    SUB_TOPICS = 本端订阅（下行 pub/*），PUB_TOPICS = 本端发布（上行 sub/*）。
"""

# ---------- broker ----------
BROKER = "192.168.0.108"   # EQ12 主机（mosquitto）的局域网 IP
PORT = 1883
CLIENT_ID = "esp32-ear"    # 每台设备唯一；重连时靠它续会话/顶掉旧连接
KEEPALIVE = 60             # 秒；引擎会以 keepalive/2 周期发 PINGREQ 保活

# ---------- 主题（器官端视角） ----------
SUB_TOPICS = [
    {
        'name': 'pub/ear',
        'qos': 0,
    },   # 下行：采集指令（载荷 b'start' / b'stop'）
    {
        'name': 'pub/speak',
        'qos': 0,
    },   # 下行：TTS 语音流（裸 PCM，EQ12 的 SpeakWorker 发布）
]
PUB_TOPICS = [
    {
        'name': 'sub/ear',
        'qos': 0,
    },   # 上行：麦克风原始音频（裸 PCM，EQ12 订阅做 ASR）
]

QOS = {t['name']: t['qos'] for t in SUB_TOPICS + PUB_TOPICS}

# ---------- 协程队列水位（满则丢最旧，防 OOM；流式音频保新鲜） ----------
OUT_Q_MAX = 32      # sub/ear 出站队列：32 块 × 640B ≈ 0.6s 音频
SPEAK_Q_MAX = 8     # pub/speak 入站队列：下行 TTS 突发时丢最旧
CMD_Q_MAX = 4       # pub/ear 指令队列
Q_CAP = {
    'pub/ear': CMD_Q_MAX,
    'pub/speak': SPEAK_Q_MAX,
    'sub/ear': OUT_Q_MAX,
}

# ---------- 音频（16kHz / 16bit / 单声道 裸 PCM，需与 EQ12 ASR/TTS 对齐） ----------
RATE = 16000
CHUNK = 640          # 一块的字节数：640B = 20ms @ 16k mono16
I2S_IBUF = 8192      # I2S DMA 缓冲字节数（约 256ms 音频，兜底调度抖动）

# I2S 外设与引脚（按你的接线改）
# 麦克风 INMP441 → I2S0（RX）
MIC = {'id': 0, 'sck': 26, 'ws': 25, 'sd': 34}
# 喇叭 MAX98357A → I2S1（TX）
SPK = {'id': 1, 'sck': 27, 'ws': 14, 'sd': 33}
