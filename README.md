# Silicon Life「硅基生命」

桌面小机器人项目 **v4 版**：把"大脑"和"身体"拆成两台设备，通过**局域网 MQTT 总线**对话。

- **EQ12 小主机（大脑 + 两只"外手"）**：跑 `eq12_server`——语音链路订阅器官上行数据（ASR 听写）→ 大模型生成回复 → TTS 合成语音下发给器官（云端能力走 DashScope）；另外 EQ12 还挂着两条**进程内工具口**：飞书（远程聊天）与桌面（直接操控这台 Windows 电脑的键鼠/滚轮/截屏）。
- **ESP32-S3-CAM（身体器官：耳 + 眼 + 嘴 + 腿 + 脸）**：跑 `esp32_client`——麦克风采音上行、喇叭播放下行语音，响应 EQ12 的"停采/恢复"指令做回声抑制；摄像头按需拍照上行（收到 `pub/eye` 拍照指令才拍）；运动指令 `pub/leg` 串行驱动云台舵机与底盘电机，每做完一条上行完成回执；表情指令 `pub/face` 驱动 ST7789 表情屏。

> 前几代（v1~v3）把大脑直接跑在 ESP32 上；v4 拆开后，ESP32 只当"哑器官"，EQ12 负责所有智能。

---

## 1. 架构总览

```
                    局域网 MQTT broker（mosquitto @ 192.168.0.108:1883，QoS0）
                                 ▲                      │
              器官发布 sub/* 上行  │                      │  服务器发布 pub/* 下行
   （麦克风音频 / 照片 / 腿完成回执）│                      │ （TTS 语音 / 采集启停 /
                                 ▼                      ▼   拍照 / 运动 / 表情指令）
┌─────────────────────────────────────────────────────────────────────────────────────┐
│  MainLoop：每主题一条队列 + 每 pub 主题一条专职发送线程 + worker 统一编排/优雅停机  │
│                                                                                     │
│  ── 语音链路（DashScope 云端能力）──                                                │
│    EarWorker   sub/ear(16k PCM) ─→ 流式 ASR ─→ asr 队列                             │
│    BrainWorker asr 文本 ─→ 大模型流式回复(成句即送) ─→ tts 队列                     │
│    SpeakWorker tts ─→ 流式 TTS(24k PCM) ─→ pub/speak 下发器官                       │
│                出声前 pub/ear 发 b'stop'，句毕发 b'start'（回声抑制）               │
│                                                                                     │
│  ── 进程内工具口（不经 MQTT，'_' 前缀内部队列；依赖缺失时 worker 自动降级跳过）──   │
│    FeishuWorker   飞书长连接收发文字/图片    _sub/feishu(收) ⇄ _pub/feishu(发)      │
│    DesktopWorker  键鼠/滚轮/截屏(操作本机)    _pub/desktop(指令入) → 执行 →         │
│                                              _sub/desktop(截图 + done 完成回执出)   │
└─────────────────────────────────────────────────────────────────────────────────────┘
┌──────────────────────────────────────────────────────────────────────────────────────────────┐
│  MainLoop：每主题一条协程队列 + 每 pub 主题一条发送任务 + worker（与 eq12 同构，线程→协程）  │
│    EarWorker    I2S 麦克风(16k) ──持续──▶ sub/ear 上行                                       │
│    SpeakWorker  pub/speak(24k) ──▶ I2S 喇叭播放（裸播，不做处理）                            │
│    CameraWorker pub/eye(b'photo') → 拍一张(OV3660) → sub/eye(JSON+base64)                    │
│    MoveWorker   pub/leg 文本指令串行执行（PCA9685 云台舵机 + DRV8833 底盘电机）              │
│                每真正做完一条 → 上行完成回执 sub/leg（文本 done:<指令>）                     │
│    ScreenWorker pub/face 表情指令 → ST7789 表情屏（眨眼/嘴部动画）                           │
└──────────────────────────────────────────────────────────────────────────────────────────────┘
```

要点：

- **pub/\* = 下行指令，sub/\* = 上行数据**：服务器发布 `pub/*`（器官订阅），器官发布 `sub/*`（服务器订阅）。两端 `config.py` 的主题/队列水位镜像配置。
- **腿是"串行动作执行器"且带完成回执**：EQ12 可向 `pub/leg` 一次连发一串动作，ESP32 一条做完（电机跑完自动停）才做下一条，并往 `sub/leg` 上行一条 `done:<指令>` 说明刚完成的是哪条——为将来大脑做"动作 → 确认完成 → 下一步"的 agentic 编排留好了同步点。
- **飞书 / 桌面是 EQ12 进程内工具口**：直连外部世界，不经 MQTT（MQTT 只服务 ESP32 器官）。大脑目前只跑语音链路，还没消费 `sub/eye`、`sub/leg`、`_sub/desktop`、`_sub/feishu` 主动"看 / 动 / 操作桌面 / 回飞书"（接线规划见 `eq12_server/src/core/readme.md`）。

## 2. 目录结构

```
silicon-life-v4/
├── README.md                  # 本文件：架构 / 协议契约 / 快速开始
├── set_dashscope_env.cmd      # 环境变量：DASHSCOPE_API_KEY、FEISHU_APP_ID/SECRET
│                               #   （含密钥，已被 gitignore，勿提交）
├── eq12_server/               # EQ12 大脑端（Windows 主机，Python ≥ 3.10，paho 线程框架）
│   ├── run.py                 #   入口：MainLoop().run()
│   ├── requirements.txt       #   依赖：paho-mqtt / dashscope / lark-oapi / pyautogui+Pillow
│   │                           #   （按能力可选，缺哪个对应 worker 自动跳过）
│   ├── README.md              #   框架设计 / 新增 worker / 停机协议 / 飞书与桌面工具口
│   └── src/
│       ├── config.py          #   broker 地址 + SUB_TOPICS / PUB_TOPICS（name + qos）
│       ├── main_loop.py       #   主循环：每主题队列 + 专职发送线程 + worker 编排 + 优雅停机
│       ├── core/readme.md     #   （规划）agentic brain 实现占位说明
│       └── workers/
│           ├── ear_worker.py       # 耳：sub/ear(16k PCM) → DashScope 流式 ASR → asr 队列
│           ├── brain_worker.py     # 脑：asr 文本 → 大模型流式回复(成句即送) → tts 队列
│           ├── speak_worker.py     # 嘴：tts → 流式 TTS(24k PCM) → pub/speak；pub/ear 回声抑制
│           ├── feishu_worker.py    # 飞书口：长连接收发文字/图片（_sub/feishu ⇄ _pub/feishu）
│           └── desktop_worker.py   # 桌面口：键鼠/滚轮/截屏（_pub/desktop 指令 →
│                                   #   _sub/desktop 截图 + {'type':'done'} 完成回执）
├── esp32_client/               # ESP32 器官端（MicroPython ≥ 1.22，asyncio 协程框架）
│   ├── boot.py                 #   开机联网（设备上那份是真实的，勿覆盖）
│   ├── main.py                 #   入口：MainLoop().run()（放根目录 = 开机自启）
│   ├── README.md               #   上传 / 烧录 / 接线 / 排障 / 协议
│   ├── docs/                   #   引脚分配与接线 / 烧录指南 / 常用命令 / 材料清单
│   ├── tests/                  #   PC 冒烟（smoke_mqtt / smoke_loop）+ 设备端最小测试
│   └── src/
│       ├── config.py           #   broker/主题/队列水位/音频/引脚 —— 唯一配置入口
│       ├── mqtt.py             #   最小 asyncio MQTT 客户端（零第三方依赖，QoS0，自动重连重订阅）
│       ├── main_loop.py        #   主循环：每主题队列 + 发送任务 + worker 编排
│       └── workers/
│           ├── ear.py          #   耳：I2S 麦克风(16k) 持续上行 sub/ear；响应 pub/ear 启停
│           ├── speak.py        #   嘴：pub/speak(24k) → I2S 喇叭播放（裸播）
│           ├── camera.py       #   眼：pub/eye b'photo' → OV3660 拍一张 → sub/eye(JSON)
│           ├── move.py         #   腿：pub/leg 串行执行（舵机+电机）→ 完成回执 sub/leg
│           └── screen.py       #   脸：pub/face 表情指令 → ST7789 表情屏
└── _device_backup/             # 旧设备备份数据（wav/pcm/日志等，gitignored，可删）
```

## 3. 主题与消息格式契约

### 3.1 MQTT 主题（EQ12 ↔ ESP32 器官）

> 方向图例：**上行** = ESP32 发布、EQ12 订阅（`sub/*`）；**下行** = EQ12 发布、ESP32 订阅（`pub/*`）。

| 主题 | 方向 | 载荷（概要） | 生产者 | 消费者 |
|---|---|---|---|---|
| `sub/ear` | ESP32 发布 → EQ12 订阅（上行） | 裸 PCM（16k / 16bit / mono） | ESP32 EarWorker | eq12 EarWorker(ASR) |
| `pub/speak` | EQ12 发布 → ESP32 订阅（下行） | 裸 PCM（24k / 16bit / mono） | eq12 SpeakWorker(TTS) | ESP32 SpeakWorker |
| `pub/ear` | EQ12 发布 → ESP32 订阅（下行） | `b'stop'` / `b'start'` | eq12 SpeakWorker | ESP32 EarWorker |
| `pub/eye` | EQ12 发布 → ESP32 订阅（下行） | `b'photo'` | eq12（大脑，待接） | ESP32 CameraWorker |
| `sub/eye` | ESP32 发布 → EQ12 订阅（上行） | JSON 信封 + base64 JPEG | ESP32 CameraWorker | eq12（视觉理解/转发，待接） |
| `pub/leg` | EQ12 发布 → ESP32 订阅（下行） | UTF-8 文本指令（同 v3 move） | eq12（大脑，待接） | ESP32 MoveWorker |
| `sub/leg` | ESP32 发布 → EQ12 订阅（上行） | UTF-8 文本回执 `done:<指令>` | ESP32 MoveWorker | eq12（大脑，待接） |
| `pub/face` | EQ12 发布 → ESP32 订阅（下行） | UTF-8 文本表情名（同 v3 screen） | eq12（大脑，待接） | ESP32 ScreenWorker |

**载荷格式明细**（上表"载荷（概要）"列的完整格式）：

- `sub/ear` —— 裸 PCM **16kHz / 16bit / mono**，每块 640B（≈20ms），麦克风连续上行。
- `pub/speak` —— 裸 PCM **24kHz / 16bit / mono**（⚠️ 与上行 16k 不同，勿混用）。
- `pub/ear` —— `b'stop'`（停采 + 清未播缓冲）/ `b'start'`（恢复采集），回声抑制用。
- `pub/eye` —— `b'photo'`；收到即拍一张，其它载荷忽略。
- `sub/eye` —— UTF-8 JSON：`{"type":"photo","time":"YYYY-mm-dd HH:MM:SS","size":<JPEG 字节>,"width":W,"height":H,"data":"<base64 JPEG>"}`。
- `pub/leg` —— UTF-8 文本指令：`forward,50,2` / `back,40` / `left,30` / `right,30,0.5` /
  `pan,90` / `tilt,45` / `stop` / `center`；兼容 `[MOVE]:` 前缀与空格分隔
  （时长参数支持 `3` / `1.5s` / `800ms` / `2秒`）。
- `sub/leg` —— UTF-8 文本回执 `done:<规范化指令>`：如 `done:forward,50,2` / `done:pan,90` /
  `done:center`；只回真做完的指令（协议详见 `esp32_client/src/workers/move.py` 文件头）。
- `pub/face` —— UTF-8 文本表情名：`idle` / `listen` / `think` / `speak` / `happy` / `sleep`
  （别名 `neutral` → `idle`；可带 `[SCR]:` 前缀，大小写不敏感）。

> eq12 框架的 `config.py` 还预留了 `pub/brain`、`sub/brain`、`pub/mouth`、`sub/mouth` 占位主题（暂无生产者/消费者），后续按需启用。

### 3.2 进程内通道（eq12 内部，不经 MQTT）

飞书与桌面是 EQ12 **进程内直连外部世界**的口，各用两条 `'_'` 前缀内部队列（`stop()` 哨兵与专职发送线程都不碰它们）：

| 通道 | 方向 | 载荷 | 说明 |
|---|---|---|---|
| `_sub/feishu` | 飞书长连接收到 → 入队 | 用户文字 / 图片消息 dict | 下游（大脑）消费，待接 |
| `_pub/feishu` | 上游入队 → worker 发出 | 回复文字 / 主动发图 dict | 大脑写入，待接 |
| `_pub/desktop` | 上游入队 → worker 执行 | `{"type":"keyboard"…}` / `"mouse"` / `"scroll"` / `"screenshot"` | 大脑写入，待接 |
| `_sub/desktop` | worker 执行完 → 入队 | 截图 `{'type':'screen',...}` + 完成回执 `{'type':'done','time':…,'command':<原始指令>}` | 下游（大脑）消费，待接 |

- 桌面的 done 与截图**同队列、按序**：如 `screenshot` 指令会先出一条截图、紧跟一条 done，下游用 `type` 区分；done 的 `command` 字段原样回传被执行的指令，方便与请求配对。
- **只回"真做完"的**：指令无效（缺参/方向错/无按键）或执行抛异常只打日志、不回执（腿同理：PCA9685 未就绪 / 未知指令 / 参数错误不发 `done:`）。

⚠️ **完成回执目前只有「腿」和「桌面」有**；眼（照片本身就是结果）与脸是单向执行、暂无完成回执，需要时可按同样方式补。

### 3.3 重要约定

- ⚠️ **上下行采样率不同**：上行 ASR 16k、下行 TTS 24k，两端分别配置，不能共用一个采样率。
- ⚠️ 照片按需推送：EQ12 想"看"时发 `pub/eye` 一条 `b'photo'`，ESP32 拍一张回一张；不是常开视频流。
- ⚠️ 运动/表情串行执行：EQ12 可一次向 `pub/leg` / `pub/face` 连发一串指令，ESP32 一条做完才做下一条（队列各 64 条）。
- ⚠️ 腿的完成回执在**动作真正做完之后**才发：电机类指令要等跑完时长自动停（`done:forward,50,2` 表示已跑满 2 秒并停稳），不是"收到指令"就回。

## 4. 快速开始

前置：

- **EQ12 主机（Windows）**：Python ≥ 3.10；局域网内已跑 Mosquitto（`listener 1883` + `allow_anonymous`）。
- **ESP32**：已刷 MicroPython ≥ 1.22 并配好 WiFi（联网在设备上的 `boot.py`）。

```bash
# ① EQ12：装依赖（仓库根目录执行；依赖按能力可选，见 eq12_server/requirements.txt）
pip install -r eq12_server/requirements.txt

# ② 起 broker
mosquitto -v

# ③ 设置环境变量（DASHSCOPE_API_KEY；用飞书再加 FEISHU_APP_ID/SECRET）
set_dashscope_env.cmd

# ④ 起服务
cd eq12_server
python run.py

# ⑤ ESP32：按 esp32_client/README.md 上传 /src + main.py 并运行器官端
```

说话 → EQ12 控制台出现 `[Brain] 听到: ...` → ESP32 喇叭即时回话。

> 不需要桌面 / 飞书功能时可不装 `pyautogui`+`Pillow` / `lark-oapi`，对应 worker 缺依赖只会打印一句提示，不影响语音链路。

## 5. 端到端数据流

**语音对话**：

```
说"你好"
  → ESP32 麦克风(16k PCM 640B/20ms 块) ── sub/ear ──▶ EQ12
  → DashScope 流式 ASR → 识别出完整句子 → BrainWorker 流式调大模型
  → 成句文本 ── tts 队列 ──▶ SpeakWorker 流式 TTS(24k PCM)
  → 出声前 pub/ear 发 b'stop'(ESP32 停采防回声) → pub/speak 下发音频
  → ESP32 喇叭播放 → 句毕 pub/ear 发 b'start'(恢复采集)
```

**动作指令（大脑尚未接线时，用 mosquitto 手动验证）**：

```bash
# 腿：发一串动作 → 订阅 sub/leg 收"每条做完"的回执
mosquitto_pub -h 192.168.0.108 -t pub/leg -m "forward,50,2"
mosquitto_pub -h 192.168.0.108 -t pub/leg -m "pan,90"
mosquitto_sub -h 192.168.0.108 -t sub/leg
#   → done:forward,50,2
#   → done:pan,90

# 眼：拍一张 → 订阅 sub/eye 收照片 JSON
mosquitto_pub -h 192.168.0.108 -t pub/eye -m photo
mosquitto_sub -h 192.168.0.108 -t sub/eye

# 脸：切表情
mosquitto_pub -h 192.168.0.108 -t pub/face -m happy
```

## 6. 文档索引

| 想看什么 | 去哪 |
|---|---|
| eq12 框架设计 / 新增 worker / 停机协议 / 飞书与桌面工具口 | `eq12_server/README.md` |
| agentic brain 规划占位 | `eq12_server/src/core/readme.md` |
| ESP32 上传 / 烧录 / 接线 / 排障 / 协议细节 | `esp32_client/README.md` + `esp32_client/docs/` |
| 具体消息协议的代码级说明 | 各 worker 文件头 docstring（如 `move.py`、`desktop_worker.py`） |
| PC 冒烟与设备端测试 | `esp32_client/tests/`（见 `esp32_client/README.md` §7） |
