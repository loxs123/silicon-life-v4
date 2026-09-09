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
CLIENT_ID = "esp32-ear-7f3a"    # 唯一 client id（曾与其它实例/脚本撞 id 互踢）
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
# pub/speak 入站队列：下行 TTS 必须"按序播完"，不能为了保新鲜丢旧音频——
# 上限给大（512 条；若每块平均 ~6KB ≈ 3MB，PSRAM 足够），只在极端异常下
# 丢最旧兜底，正常播放绝不抢占/跳句。
SPEAK_Q_MAX = 512
CMD_Q_MAX = 4       # pub/ear 指令队列
Q_CAP = {
    'pub/ear': CMD_Q_MAX,
    'pub/speak': SPEAK_Q_MAX,
    'sub/ear': OUT_Q_MAX,
}

# ---------- 音频（裸 PCM；格式须与 eq12_server 两侧服务对齐） ----------
# 回声抑制恢复保护：EQ12 在整句语音"发完"时就发 b'start'，但 ESP32 喇叭
# 可能还有缓冲尾巴在播。ear 收到 b'start' 后要等喇叭静默满 ECHO_GUARD_MS
# 才恢复上行，避免录到自己声音造成自答循环。回声严重就调大、卡顿就调小。
ECHO_GUARD_MS = 400

# 上行麦克风 → EQ12 的 ASR(dashscope)：16kHz / 16bit / mono
MIC_RATE = 16000
MIC_CHUNK = 640          # 640B = 20ms @ 16k mono16
# 下行喇叭 ← EQ12 的 TTS(qwen3-tts)：24kHz / 16bit / mono —— 该模型固定输出，
# 见 eq12_server/src/workers/speak_worker.py 的"下行音频格式契约"。两个方向
# 采样率不同，必须分开配！
SPK_RATE = 24000
# 写块粒度 ≈ 31ms（48000B/s ÷ 32，参考 v3 speaker.py：块太小写调用过密反而卡）
SPK_CHUNK = 1500
# DMA 缓冲：v3 实测 16384 抗抖最优；过大(32768)反而更糟
I2S_IBUF = 16384

# I2S 外设与引脚（ESP32-S3-CAM，见 docs/引脚分配与接线.md）
# 麦克风 INMP441 → I2S0（RX）：SCK=GPIO14 / WS=GPIO1 / SD=GPIO2
MIC = {'id': 0, 'sck': 14, 'ws': 1, 'sd': 2}
# 喇叭 MAX98357 → I2S1（TX）：BCLK=GPIO42 / LRC=GPIO41 / DIN=GPIO21
SPK = {'id': 1, 'sck': 42, 'ws': 41, 'sd': 21}
