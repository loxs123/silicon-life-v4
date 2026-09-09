# Silicon Life v4 —— EQ12「硅基生命」

桌面小机器人项目 **v4 版**：把"大脑"和"身体"拆成两台设备，通过**局域网 MQTT 总线**对话。

- **EQ12 小主机（大脑）**：跑 `eq12_server`——订阅器官上行数据（ASR 听写）→ 大模型生成回复 → TTS 合成语音下发给器官。云端能力走 DashScope。
- **ESP32-S3-CAM（身体器官：耳 + 眼 + 嘴 + 腿 + 脸）**：跑 `esp32_client`——麦克风采音上行、喇叭播放下行语音，同时响应 EQ12 的"停采/恢复"指令做回声抑制；摄像头按需拍照上行（收到 `pub/eye` 拍照指令才拍）；运动指令 `pub/leg` 串行驱动云台舵机与底盘电机；表情指令 `pub/face` 驱动 ST7789 表情屏。

> 前几代（v1~v3）把大脑直接跑在 ESP32 上；v4 拆开后，ESP32 只当"哑器官"，EQ12 负责所有智能。

---

## 1. 架构总览

```
                     局域网 MQTT broker（mosquitto @ 192.168.0.108:1883，QoS0）
                                  ▲                    │
             器官发布 sub/* 上行   │                    │  服务器发布 pub/* 下行
              （ESP32 麦克风音频）  │                    │  （TTS 语音 / 采集指令）
                                  ▼                    ▼
┌───────────────────────────  eq12_server（EQ12 主机，Python + paho）──────────────┐
│  MainLoop：每主题队列 + 专职发送线程 + worker                                     │
│    EarWorker(sub/ear)  ─→  DashScope 流式 ASR(16k PCM)  ─→  asr 队列             │
│    BrainWorker(asr)    ─→  大模型流式回复(成句即送)      ─→  tts 队列             │
│    SpeakWorker(tts)    ─→  DashScope 流式 TTS(24k PCM)  ─→  pub/speak            │
│                          出声前 pub/ear 发 b'stop'，句毕发 b'start'（回声抑制）   │
└──────────────────────────────────────────────────────────────────────────────────┘
┌───────────────────────────  esp32_client（ESP32-S3，MicroPython + asyncio）───────┐
│  MainLoop：每主题队列 + 发送任务 + worker（与 eq12 同构，线程→协程）               │
│    EarWorker  ：I2S 麦克风(16k) ──持续──▶ sub/ear 上行                              │
│    SpeakWorker：pub/speak(24k) ──▶ I2S 喇叭播放（裸播，不做处理）                 │
│    CameraWorker：pub/eye(b'photo') → 拍一张(OV3660) → sub/eye(JSON+base64)         │
│    MoveWorker  ：pub/leg 指令串行执行（PCA9685: 云台 CH0/1 + 电机 CH12–15）        │
│    ScreenWorker：pub/face 表情指令 → ST7789 表情屏（眨眼/嘴动画）                  │
│    pub/ear 指令：b'stop' 停采并清未播缓冲 / b'start' 恢复                          │
└──────────────────────────────────────────────────────────────────────────────────┘
```

## 2. 目录结构

| 路径 | 说明 |
|---|---|
| `eq12_server/` | EQ12 大脑端：MQTT 中枢框架 + ASR/LLM/TTS worker（详见其 README.md） |
| `esp32_client/` | ESP32 器官端：MicroPython asyncio 客户端（详见其 README.md） |
| `requirements.txt` | PC 端 Python 依赖（paho-mqtt/dashscope/lark-oapi/pyautogui，含可选说明） |
| `demos/` | eq12 侧的 MQTT / 线程 / 队列 / ASR / TTS 原型实验 |
| `set_dashscope_env.cmd` | 设置 `DASHSCOPE_API_KEY`（含密钥，已被 gitignore，勿提交） |
| `_device_backup/` | 从旧设备备份出的历史数据（wav/pcm/日志等，gitignored，可删） |

## 3. 主题与消息格式契约

| 主题 | 方向 | 载荷 | 生产者 | 消费者 |
|---|---|---|---|---|
| `sub/ear` | 器官 → 服务器 | 裸 PCM **16kHz / 16bit / mono**（原始麦克风） | ESP32 EarWorker | eq12 EarWorker(ASR) |
| `pub/speak` | 服务器 → 器官 | 裸 PCM **24kHz / 16bit / mono**（TTS 输出） | eq12 SpeakWorker(TTS) | ESP32 SpeakWorker |
| `pub/ear` | 服务器 → 器官 | `b'stop'` / `b'start'`（采集启停，回声抑制） | eq12 SpeakWorker | ESP32 EarWorker |
| `pub/eye` | 服务器 → 器官 | `b'photo'`（拍照指令，一指令一张） | eq12（大脑，待接） | ESP32 CameraWorker |
| `sub/eye` | 器官 → 服务器 | UTF-8 JSON：`{"type":"photo","time":...,"size":n,"width":W,"height":H,"data":"<base64 JPEG>"}` | ESP32 CameraWorker | eq12（视觉理解/转发，待接） |
| `pub/leg` | 服务器 → 器官 | UTF-8 文本指令（同 v3 move）：`forward,50,2` / `pan,90` / `stop` / `center`… | eq12（大脑，待接） | ESP32 MoveWorker |
| `pub/face` | 服务器 → 器官 | UTF-8 文本指令（同 v3 screen）：`speak` / `happy` / `sleep`（可带 `[SCR]:` 前缀） | eq12（大脑，待接） | ESP32 ScreenWorker |

⚠️ **上下行采样率不同**（上行 ASR 16k、下行 TTS 24k），两端分别配置，不能共用一个采样率。
⚠️ 照片按需推送：EQ12 想"看"时发 `pub/eye` 一条 `b'photo'`，ESP32 拍一张回一张；不是常开视频流。
⚠️ 运动/表情串行执行：EQ12 可一次向 `pub/leg` / `pub/face` 连发一串指令，ESP32 一条做完才做下一条（队列各 64 条）。

## 4. 快速开始

前置：Python ≥ 3.10、EQ12 主机上已跑 Mosquitto（局域网可连）、ESP32 已刷 MicroPython ≥ 1.22。

```bash
# ① EQ12：装依赖 + 起 broker + 起服务
pip install -r requirements.txt
mosquitto -v                      # 需允许局域网接入(listener 1883 + allow_anonymous)
set_dashscope_env.cmd             # 或手动 set DASHSCOPE_API_KEY=sk-xxx
python run.py                     # 在 eq12_server/ 下

# ② ESP32：按 esp32_client/README.md 上传并运行器官端
```

说话 → EQ12 控制台出现 `[Brain] 听到: ...` → ESP32 喇叭即时回话。

## 5. 端到端数据流

```
说"你好"
  → ESP32 麦克风(16k PCM 640B/20ms 块) ── sub/ear ──▶ EQ12
  → DashScope 流式 ASR → 识别出完整句子 → BrainWorker 流式调大模型
  → 成句文本 ── tts 队列 ──▶ SpeakWorker 流式 TTS(24k PCM)
  → 出声前 pub/ear 发 b'stop'(ESP32 停采防回声) → pub/speak 下发音频
  → ESP32 喇叭播放 → 句毕 pub/ear 发 b'start'(恢复采集)
```

## 6. 音量

下行音量衰减在 **EQ12 端**做（`eq12_server/src/workers/speak_worker.py` 的 `VOLUME_DIV`，
默认 3 = 1/8 ≈ -18dB）。ESP32 只做裸播放。

## 7. 当前状态

- [x] eq12_server：MQTT 中枢 + EarWorker(ASR)/BrainWorker(LLM)/SpeakWorker(TTS) 全链路
- [x] esp32_client：与 eq12 同构的 asyncio 器官端，自研最小 MQTT 客户端（零第三方依赖）
- [x] 端到端语音对话跑通（含回声抑制、断线自动重连）
- [x] esp32 端「眼睛」拍照链路：`pub/eye`(b'photo') → OV3660 拍一张 → `sub/eye`(JSON+base64)
- [x] esp32 端「腿」串行动作执行器：`pub/leg` 文本指令 → PCA9685 云台舵机 + DRV8833 底盘电机
- [x] esp32 端「脸」表情屏：`pub/face` 文本指令 → ST7789（idle/listen/think/speak/happy/sleep + 眨眼动画）
- [x] eq12 端「飞书」网关：`FeishuWorker` 直连飞书 OpenAPI 收发文字/图片
      （`_sub/feishu` 收、`_pub/feishu` 发，进程内队列不经 MQTT；凭据放
      `set_dashscope_env.cmd`）—— brain 消费/回写接线待做（见 eq12_server/README §6.1）
- [x] eq12 端「桌面」操作：`DesktopWorker` 消费 `_pub/desktop`（keyboard/mouse/
      scroll/screenshot 指令）并截图入 `_sub/desktop`（JPEG base64，字段对齐
      `sub/eye`）—— brain 读图/发指令接线待做（见 eq12_server/README §6.2）
- [ ] eq12 端消费 `sub/eye`（视觉大模型/飞书/存卡）+ 触发 `pub/eye`/`pub/leg`/`pub/face`（大脑主动想看/想动/换表情）—— 待接
- [ ] 4G(Cat.1) 场景 / 更多器官（head…）—— 待扩展

## 8. 文档索引

| 想看什么 | 去哪 |
|---|---|
| eq12 框架设计 / 新增 worker / 停机协议 | `eq12_server/README.md` |
| ESP32 烧录 / 上传 / 接线 / 排障 | `esp32_client/README.md` + `esp32_client/docs/` |
| MQTT/ASR/TTS 最小可跑示例 | `demos/` |
