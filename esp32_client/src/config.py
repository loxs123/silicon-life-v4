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
CLIENT_ID = "esp32-node-7f3a"   # 唯一 client id（曾与其它实例/脚本撞 id 互踢）
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
    {
        'name': 'pub/eye',
        'qos': 0,
    },   # 下行：拍照指令（载荷 b'photo'，收到拍一张推 sub/eye）
    {
        'name': 'pub/leg',
        'qos': 0,
    },   # 下行：运动指令（文本，格式同 v3 move：如 "forward,50,2" / "[MOVE]:pan,90"）
    {
        'name': 'pub/face',
        'qos': 0,
    },   # 下行：表情指令（文本，格式同 v3 screen：如 "speak" / "[SCR]:happy"）
]
PUB_TOPICS = [
    {
        'name': 'sub/ear',
        'qos': 0,
    },   # 上行：麦克风原始音频（裸 PCM，EQ12 订阅做 ASR）
    {
        'name': 'sub/eye',
        'qos': 0,
    },   # 上行：照片（UTF-8 JSON 信封 + base64 JPEG，EQ12 订阅消费）
    {
        'name': 'sub/leg',
        'qos': 0,
    },   # 上行：腿的指令完成回执（文本 done:<指令>，EQ12 订阅做动作同步）
]

QOS = {t['name']: t['qos'] for t in SUB_TOPICS + PUB_TOPICS}

# ---------- 协程队列水位（满则丢最旧，防 OOM；流式音频保新鲜） ----------
OUT_Q_MAX = 32      # sub/ear 出站队列：32 块 × 640B ≈ 0.6s 音频
# pub/speak 入站队列：下行 TTS 必须"按序播完"，不能为了保新鲜丢旧音频——
# 上限给大（512 条；若每块平均 ~6KB ≈ 3MB，PSRAM 足够），只在极端异常下
# 丢最旧兜底，正常播放绝不抢占/跳句。
SPEAK_Q_MAX = 512
CMD_Q_MAX = 4       # pub/ear 指令队列（pub/eye 拍照指令同样很小，共用此值）
PHOTO_Q_MAX = 2     # sub/eye 出站队列：照片大、按需拍，只留最新 2 张防断线积压
# pub/leg 指令队列：EQ12 可能一次下发一串动作序列（前进/转向/转头…），给大一点，
# worker 按序一条做完再做下一条；满则丢最旧（只丢还没执行的最老动作）
LEG_Q_MAX = 64
# sub/leg 完成回执出站队列：腿每执行完一条 pub/leg 上行一条 done 文本，很轻量；
# 满则丢最旧（保新鲜，正常瞬时一条条发不会积压）
LEG_DONE_Q_MAX = 16
# pub/face 指令队列：同理，EQ12 一次下发一串表情（唱歌/表演/多轮对话），给大一点
FACE_Q_MAX = 64
Q_CAP = {
    'pub/ear': CMD_Q_MAX,
    'pub/speak': SPEAK_Q_MAX,
    'pub/eye': CMD_Q_MAX,
    'pub/leg': LEG_Q_MAX,
    'pub/face': FACE_Q_MAX,
    'sub/ear': OUT_Q_MAX,
    'sub/eye': PHOTO_Q_MAX,
    'sub/leg': LEG_DONE_Q_MAX,
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

# ---------- 摄像头（眼睛 OV3660，见 docs/引脚分配与接线.md「摄像头 OV3660」节） ----------
# 帧大小：默认 QVGA(320x240)。想更清晰改成 'VGA'(640x480)/'SVGA'(800x600) 等，
# 并把 CAM_W/CAM_H 同步改（FrameSize 名字与 CAM_W/H 必须配套！8MB PSRAM 够用）。
CAM_FRAME_SIZE = 'QVGA'
CAM_W, CAM_H = 320, 240
JPEG_QUALITY = 92                  # 越高越清楚、文件越大
CAM_PIXEL_FMT = 'RGB565_BE'        # 照片颜色不对时改 'RGB565_LE'
# 摄像头信号 → GPIO（24P FPC 板内直插，与卖家 camera_demo.py 一致；勿挪作他用）
CAM_PINS = dict(
    data_pins=[11, 9, 8, 10, 12, 18, 17, 16],
    vsync_pin=6, href_pin=7, sda_pin=4, scl_pin=5,
    pclk_pin=13, xclk_pin=15, xclk_freq=20000000,
    powerdown_pin=-1, reset_pin=-1,
)
# 拍照前暖帧：闲置久了 AE/AWB 未收敛，直接单帧拍会发糊/偏暗偏亮。每次拍照前
# 连拍 SNAP_WARM_FRAMES 帧丢弃再取正式帧，画面清楚；期间的 await 也让出事件循环。
SNAP_WARM_FRAMES = 6
SNAP_WARM_STEP_MS = 100

# ---------- 运动（腿：PCA9685 → SG90 云台 + DRV8833 电机，见 docs/引脚分配与接线.md） ----------
# 通道-器件对应与 v3 motor_actor/move 实测一致；改动只在这里
MOVE = {
    'i2c_id': 0, 'sda': 47, 'scl': 48,     # PCA9685 I2C（与屏/MIC 不冲突）
    'addr': 0x40, 'freq': 50,              # 地址 0x40，PWM 50Hz（舵机标准）
    'ch_pan': 0, 'ch_tilt': 1,             # SG90 云台：水平(pan) / 俯仰(tilt)
    'ch_left_a': 12, 'ch_left_b': 13,      # DRV8833 AIN1/AIN2 → 左电机
    'ch_right_a': 14, 'ch_right_b': 15,    # DRV8833 BIN1/BIN2 → 右电机
    # 电机方向校准（v3 实测：左电机线序反，软件反转）
    'invert_left': True, 'invert_right': False,
    # 舵机机械行程限幅（防堵转），中位都是 90
    'pan_min': 60, 'pan_max': 120,
    'tilt_min': 45, 'tilt_max': 135,
}
# 电机"一条指令动一小段就自动停"（默认持续秒数；指令第 3 参可覆盖）
DRIVE_FORWARD_SECONDS = 1.5   # forward/back 默认
DRIVE_TURN_SECONDS = 1.0      # left/right 默认
DRIVE_SECONDS_MIN = 0.1       # 最短持续（防"0 秒"误触成急刹脉冲）
DRIVE_SECONDS_MAX = 10.0      # 最长持续（超长钳到 10 秒）

# ---------- 屏（脸：1.54" ST7789 240x240，见 docs/引脚分配与接线.md「1.54 寸屏 ST7789」节） ----------
SCREEN = {
    'w': 240, 'h': 240,
    'spi_id': 1,               # ⚠️ 必须 SPI(1)：实测 SPI(2) 会让板子复位
    'spi_hz': 20000000,        # SPI 时钟 20MHz
    'sck': 43, 'mosi': 44,     # ⚠️ 占板载 TTL-USB 口：跑屏时别插 TTL 线，烧录/REPL 走 OTG
    'dc': 46, 'cs': 3,         # ⚠️ 都是 strapping 脚：别加上下拉（CS 吃板内 12K 上拉）
    'madctl': 0x60,            # 帧方向：0x00=0° 0x60=90° 0xC0=180° 0xA0=270°；镜像 ±0x40
    'chunk': 4096,             # SPI 分块推屏粒度（一次 write 的字节数）
}
