

import os

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


# ======================= 队列名 =======================
# 队列清单 / 载荷格式见 core/queues.md。MQTT 主题名用上面的 SUB_TOPICS / PUB_TOPICS。
QUEUE_ASR = 'asr'                   # 耳朵 → 大脑：一句识别文本
QUEUE_TTS = 'tts'                   # 大脑 → 嘴：要说的文本
QUEUE_EAR_IN = 'sub/ear'            # 耳朵：ESP32 上行原始音频
QUEUE_SPEAK_OUT = 'pub/speak'       # 嘴：下行 TTS 语音流（ESP32 订阅播放）
QUEUE_EAR_CTRL = 'pub/ear'          # 嘴 → 耳朵：采集启停（回声抑制）
QUEUE_LEG_PUB = 'pub/leg'           # 腿：运动指令（文本 动词[,参数[,参数]]）
QUEUE_LEG_SUB = 'sub/leg'           # 腿：动作完成回执（文本 done:<规范化指令>）
QUEUE_EYE_PUB = 'pub/eye'           # 眼睛：拍照指令（bytes b'photo'）
QUEUE_EYE_SUB = 'sub/eye'           # 眼睛：拍完的照片（bytes JSON，含 base64）
QUEUE_FACE_PUB = 'pub/face'         # 脸：表情（文本 idle/listen/think/…）
QUEUE_FEISHU_SUB = '_sub/feishu'    # 飞书收：收到消息入队
QUEUE_FEISHU_PUB = '_pub/feishu'    # 飞书发：出站消息队列
QUEUE_DESKTOP_SUB = '_sub/desktop'  # 桌面出：截图 + 完成回执
QUEUE_DESKTOP_PUB = '_pub/desktop'  # 桌面入：电脑控制指令
QUEUE_DELAY_SUB = '_sub/delay'      # 延迟出：到点的那条消息 {'text': …}
QUEUE_DELAY_PUB = '_pub/delay'      # 延迟入：{'text': …, 'in': 秒}

# ======================= 凭据（环境变量，见 set_dashscope_env.cmd）=======================
DASHSCOPE_API_KEY = os.environ.get('DASHSCOPE_API_KEY', '')
FEISHU_APP_ID = os.environ.get('FEISHU_APP_ID', '')
FEISHU_APP_SECRET = os.environ.get('FEISHU_APP_SECRET', '')
SILICONFLOW_API_KEY = os.environ.get('SILICONFLOW_API_KEY', '')
DEEPSEEK_API_KEY = os.environ.get('DEEPSEEK_API_KEY', '')

# ======================= 大脑 / 大模型（硅基流动 SiliconFlow，OpenAI 兼容）=======================
SILICONFLOW_BASE = 'https://api.siliconflow.cn/v1'
LLM_MODEL = 'deepseek-ai/DeepSeek-V4.1-Flash'          # 纯文本
LLM_MODEL_VL = 'deepseek-ai/DeepSeek-V4.1-Flash'    # 带图（image_url / data URL）时自动换它
LLM_MAX_TOKENS = 2048
LLM_TEMPERATURE = 0.3
LLM_TIMEOUT = 60              # 秒

# ======================= 耳朵 / ASR =======================
ASR_MODEL = 'qwen-audio-3.0-asr-flash-streaming'
ASR_FORMAT = 'pcm'            # int16 pcm
ASR_SAMPLE_RATE = 16000       # 支持 8000 / 16000
ASR_CHANNELS = 1              # 单声道
ASR_BLOCK_SIZE = 512          # 读块大小（喂 ASR 本身没有 512 限制）

# ======================= 嘴 / TTS =======================
TTS_WS_URL = 'wss://dashscope.aliyuncs.com/api-ws/v1/realtime'
# 专属接入点示例：'wss://xxx.cn-beijing.maas.aliyuncs.com/api-ws/v1/realtime'
TTS_MODEL = 'qwen3-tts-flash-realtime'
TTS_VOICE = 'Chelsie'         # 音色
TTS_SPEED = 1.2               # 语速倍率：0.5~2.0（1.0 正常）
TTS_CONNECT_TIMEOUT = 6.0     # 建连（含后台预热）最长等待秒数
TTS_SENTENCE_TIMEOUT = 30.0   # 单句合成超时秒数，防网络异常永久卡住
# 下行音量（数字衰减，在服务器侧压好再发 pub/speak，ESP32 只裸播）：
# int16 PCM 每样本右移 TTS_VOLUME_DIV 位，每移 1 位 = -6dB
#   1 原声 0dB | 2 = 1/4 -12dB | 3 = 1/8 -18dB | 4 = 1/16 -24dB
# MAX98357 GAIN 悬空时增益偏高、实测偏吵 → 现在 4（1/16）；太吵 +1，太轻 -1。
TTS_VOLUME_DIV = 4
EAR_STOP = b'stop'            # 出声前推给耳朵：停采，防 mic 收到自己的声音
EAR_START = b'start'          # 播完/放弃后推给耳朵：恢复采集

# ======================= 飞书 =======================
# 出站兜底会话：出站消息既没带 chat_id、也还没收到过任何入站消息时用它。
# 日常用不着（省略 chat_id 会自动回「消息来的那个会话」）；配它是为了进程
# 刚重启、还没人说话时也能主动开口。oc_ 开头，从飞书消息链接或开发者后台拿。
# 留空 = 不兜底，此时只打一句日志并放弃发送。
FEISHU_DEFAULT_CHAT_ID = ''

# ======================= 桌面 =======================
DESKTOP_HOLD_S = 0.05         # keyboard 指令缺省按压时长（秒）
DESKTOP_JPEG_QUALITY = 85     # 截图 JPEG 质量（0-100）

# ======================= 延迟消息（DelayWorker）=======================
# "15 分钟之后提醒我喝水"不能在 hook 里 sleep（会拖死 brain 主循环）：上游投
# {'text': …, 'in': <秒>} 进 _pub/delay，DelayWorker 守时钟，到点把「多久之前你让我
# 做什么」推进 _sub/delay。只碰这两条队列，不关联任何别的队列。
DELAY_POLL_S = 1.0            # 主循环每轮睡多久（秒）：到点精度就是这个量级
# 到点推出去的那句话，占位符：{ago}（'15 分钟之前' / '刚刚'）、{text}
DELAY_ECHO_TEMPLATE = '{ago}你让我{text}，现在到点了，你来接着办。'

# ======================= 睡眠 / dream =======================
# 白天跑 Decision，晚上跑 Dream —— 两者**时间上互斥，不并发**，
# 所以不需要抢占 / 异步 / 预算守卫。判据见 workers/brain_worker.py 的 is_night()，
# 一夜一轮、跑完睡到 DREAM_NIGHT_END 收工的逻辑见 core/dream.py。
DREAM_NIGHT_START = 23        # 几点开始做梦（24 小时制）
DREAM_NIGHT_END = 7           # 几点醒；START > END 表示跨午夜
DREAM_POLL_S = 60.0           # 已废弃：dream 不再 while 轮询，留着只为不打断别处引用