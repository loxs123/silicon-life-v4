# esp32_client —— 器官端（耳 + 眼 + 嘴 + 腿 + 脸）

跑在 **ESP32-S3-CAM**（N16R8）上的 MicroPython 客户端，是 EQ12「硅基生命」的**身体器官**：

- **ear**：I2S 麦克风（INMP441）采集 16k 裸 PCM，持续发布到 `sub/ear`，交给 EQ12 的 ASR；
- **eye（camera）**：OV3660 摄像头。**不常开预览**：订阅 `pub/eye`，收到拍照指令 `b'photo'` 才拍一张，把照片（JSON 信封 + base64 JPEG）发布到 `sub/eye`；
- **leg（move）**：PCA9685 + DRV8833。订阅 `pub/leg` 运动指令，**串行执行**——云台舵机（pan/tilt）就位、底盘电机（forward/back/left/right）跑完指定时长自动停，一条做完才做下一条；每做完一条往 `sub/leg` 上行完成回执（文本 `done:<指令>`，说明刚完成哪条）；
- **face（screen）**：1.54" ST7789 表情屏。订阅 `pub/face` 表情指令（idle/listen/think/speak/happy/sleep），一条画完才切下一条；自带眨眼 + 说话嘴部动画；
- **speak**：订阅 `pub/speak` 的 24k 裸 PCM（EQ12 TTS），直接喂 I2S 喇叭（MAX98357）播放；
- 响应 EQ12 的 `pub/ear` 采集指令（`b'stop'` / `b'start'`），实现回声抑制。

代码结构与 `eq12_server` **同构**（config → main_loop 队列路由 → workers），只是线程换成了 **asyncio 协程**、paho 换成了本仓库自研的**最小 asyncio MQTT 客户端**（`src/mqtt.py`，QoS0，仅依赖 asyncio + struct，**零第三方库**）。

---

## 1. 目录结构

```
esp32_client/
├── boot.py                # 开机联网脚本（真实 WiFi/NTP/WebREPL 版，勿覆盖）
├── main.py                # 入口：asyncio.run(MainLoop().run())（上传到设备根目录可开机自启）
├── src/                   # 项目包（上传到设备 /src）
│   ├── config.py          # broker/主题/队列水位/音频/I2S 引脚 —— 唯一配置入口
│   ├── mqtt.py            # 最小 asyncio MQTT 客户端（对应 eq12 的 paho）
│   ├── main_loop.py       # 主循环：队列路由 + 任务编排 + 停机（对应 eq12 的 main_loop）
│   └── workers/
│       ├── ear.py         # 麦克风采集 → 上行 sub/ear；响应 pub/ear 指令
│       ├── camera.py      # 眼：pub/eye 收 b'photo' → 拍一张 → 上行 sub/eye
│       ├── speak.py       # 下行 pub/speak → I2S 播放（裸播）
│       ├── move.py        # 腿：pub/leg 运动指令串行执行（PCA9685 舵机+电机）
│       └── screen.py      # 脸：pub/face 表情指令 → ST7789 表情屏（眨眼/嘴动画）
├── tests/                 # 测试与调试脚本（见 §7）
│   ├── smoke_mqtt.py      # PC：MQTT 引擎冒烟（假 broker）
│   ├── smoke_loop.py      # PC：MainLoop 全链路冒烟（假 machine + 假 broker）
│   ├── mqtt_connect_test.py  # 设备：MQTT 连接稳定性最小测试
│   ├── mqtt_pub_storm.py  # 设备：持续发布压力测试
│   └── boot_debug.py      # 最小调试 boot：不连 WiFi/不校时，排查"开机卡死"
└── docs/
    ├── 引脚分配与接线.md   # 各部件 GPIO 接线表（麦 14/1/2，功放 42/41/21…）
    ├── 烧录指南.md         # 固件刷写 / 文件上传 / WebREPL / 运行调试
    ├── 常用命令.md         # 高频命令速查
    └── 现有材料清单.md     # 硬件清单与结构说明
```

## 2. 硬件

- 主控：ESP32-S3-CAM（N16R8：16MB Flash / 8MB PSRAM），MicroPython ≥ 1.22（需 `machine.I2S` + `asyncio`）
- 麦克风：INMP441（I2S，**16k 上行**）→ SCK=GPIO14 / WS=GPIO1 / SD=GPIO2
- 功放+喇叭：MAX98357（I2S，**24k 下行**）→ BCLK=GPIO42 / LRC=GPIO41 / DIN=GPIO21
- 摄像头：OV3660（300 万像素）→ 24P FPC 直插板载座，**板内已连 GPIO4–18（除 GPIO14）**，无需额外接线
- 运动：SG90 二自由度云台（摄像头"头"）+ DRV8833 双电机底盘，PWM 全走 PCA9685（I2C GPIO47/48，通道见下）
- 表情屏：1.54" ST7789（240×240）→ SPI(1)：SCK=GPIO43 / MOSI=GPIO44 / DC=GPIO46 / CS=GPIO3（⚠️ 跑屏时别插 TTL 线）

> 详细接线与风险提示见 `docs/引脚分配与接线.md`（⚠️ 含 strapping 脚、板载 RGB 共用 GPIO48 等坑）。

## 3. 上传与运行（USB）

前置：`pip install mpremote`，板子走 **OTG USB-C 口**（TTL 口被屏幕占用）。以 COM4 为例：

```powershell
# ① 清理 PC 端 __pycache__（避免整包上传带上去）
Get-ChildItem src -Recurse -Directory -Filter __pycache__ | Remove-Item -Recurse -Force

# ② 上传（boot.py 不覆盖——设备上那份是真实的联网脚本）
mpremote connect COM4 fs rm -r /src          # 若设备上有旧包先删
mpremote connect COM4 fs cp -r src :          # /src 整包
mpremote connect COM4 fs cp main.py :         # 根目录 main.py（放上去=开机自启；调试期可先不放）

# ③ 软复位运行
mpremote connect COM4 reset
mpremote connect COM4 repl
```

**MicroPython 开机顺序**：`/boot.py`（联网）→ `/main.py`（若有，自动运行主程序）。
WebREPL 免线更新 / 固件刷写见 `docs/烧录指南.md`。

### 调试期推荐做法（避免"一直有 main"的混乱）

1. **设备根目录不放假 main.py** → 开机只停到 REPL `>>>`；
2. 手动启动，**一次只跑一个实例**：

```python
import asyncio; from src.main_loop import MainLoop; asyncio.run(MainLoop().run())
```

> 重复 paste 会被 `[MainLoop] 已在运行，忽略重复启动` 拦住（防双实例同 id 互踢）。

3. 全部调通后，再把 `main.py` 放回根目录即可开机自启。

## 4. 配置（src/config.py，唯一配置入口）

| 配置 | 默认 | 说明 |
|---|---|---|
| `BROKER` / `PORT` | `192.168.0.108:1883` | EQ12 主机（mosquitto）的局域网 IP |
| `CLIENT_ID` | `esp32-node-7f3a` | **必须唯一**！两台设备/脚本用同 id 会互踢（"连上→断开"循环） |
| `SUB_TOPICS` | `pub/ear`、`pub/speak`、`pub/eye`、`pub/leg`、`pub/face` | 本端订阅 = 服务器下行 |
| `PUB_TOPICS` | `sub/ear`、`sub/eye`、`sub/leg` | 本端发布 = 服务器上行（`sub/leg` = 腿的完成回执） |
| `MIC_RATE` / `MIC_CHUNK` | 16000 / 640B(20ms) | 上行麦克风，与 EQ12 ASR 对齐 |
| `SPK_RATE` / `SPK_CHUNK` | 24000 / 960B(20ms) | 下行喇叭，与 EQ12 TTS 对齐 |
| `MIC` / `SPK` | GPIO 见上 | I2S id + 引脚（改线只动这里） |
| `CAM_FRAME_SIZE` / `CAM_W/H` / `JPEG_QUALITY` | QVGA / 320×240 / 92 | 拍照分辨率/画质（改配置不用动代码） |
| `MOVE` / `DRIVE_*_SECONDS` | 通道/限幅/方向校准/默认时长 | 运动通道与参数（PCA9685 CH0/1/12–15，见 docs） |
| `SCREEN` | SPI(1)/引脚/帧方向 | 表情屏参数（见 docs「1.54 寸屏 ST7789」节） |
| 队列水位 | `OUT_Q_MAX=32`、`LEG_Q_MAX=64`、`FACE_Q_MAX=64`、`PHOTO_Q_MAX=2` 等 | 满则丢最旧，防 OOM；leg/face 给大以支持动作/表情序列 |

WiFi 在 **boot.py**（根目录那份真实的），不在这里。

## 5. 消息协议契约（与 eq12_server 严格对齐）

| 主题 | 方向 / 载荷格式 | 说明 |
|---|---|---|
| `sub/ear`（上行） | 16k / 16bit / mono 裸 PCM | dashscope 流式 ASR 的固定输入格式 |
| `pub/speak`（下行） | 24k / 16bit / mono 裸 PCM | qwen3-tts 固定输出，**≠ 上行 16k** |
| `pub/ear` | `b'stop'` / `b'start'` | 回声抑制：出声前停采、句毕恢复 |
| `pub/eye`（下行） | `b'photo'` | 拍照指令：收到即拍一张（其它载荷忽略） |
| `sub/eye`（上行） | UTF-8 JSON 信封，`data` 为 base64 JPEG | 按需拍照，一指令一图；**不是常开视频流** |
| `pub/leg`（下行） | UTF-8 文本指令（同 v3 move） | **串行动作**：一条做完才做下一条；队列 64 条可放动作序列 |
| `sub/leg`（上行） | UTF-8 文本回执：`done:<指令>`（如 `done:forward,50,2`） | 腿**真做完**一条 `pub/leg` 就回执一条，说明刚完成哪条（电机跑完自动停后才发）；EQ12 订阅做动作同步 |
| `pub/face`（下行） | UTF-8 文本指令（同 v3 screen） | **串行表情**：一条画完才切下一条；队列 64 条可放表情序列 |

`pub/leg` 指令示例（载荷 = 指令文本的 UTF-8 字节）：

```text
forward,50,2      # 前进 50%，跑 2 秒自动停（支持 1.5s / 800ms / 2秒）
back,40           # 后退 40%（默认 1.5s）
left,30           # 原地左转 30%（默认 1.0s）
right,30,0.5      # 原地右转 0.5 秒
pan,90  / tilt,45 # 云台水平/俯仰转指定角度（限幅内）
stop              # 电机立即停止
center            # 云台回中(90/90) + 电机停
# 也兼容旧格式前缀 "[MOVE]:pan,90" 与空格分隔 "forward 50 2"
```

`pub/face` 指令示例（载荷 = 表情名的 UTF-8 字节，可带旧前缀 `[SCR]:`）：

```text
idle      # 待机（微笑）
listen    # 聆听（眼睛下移 O 嘴）
think     # 思考（眼球上瞟）
speak     # 说话（嘴部开合动画）
happy     # 开心（咧嘴）
sleep     # 睡觉（闭眼 zzz）
neutral   # 别名 = idle
# 如 "[SCR]:happy" / "[SCR]:speak"，大小写不敏感
```

`sub/eye` 照片消息示例（单条 MQTT 载荷，可整体 `json.loads`）：

```json
{"type":"photo","time":"2025-06-01 12:00:00","size":48213,
 "width":320,"height":240,"data":"<base64 JPEG>"}
```

> EQ12 端消费：`b64decode(data)` 即 JPEG 文件字节（与 v3 camera actor 的
> 照片消息同构，方便将来接视觉大模型 / 飞书 / 存 SD 卡）。
> 拍照参数（分辨率/画质/引脚/暖帧）在 `src/config.py` 的 `CAM_*`/`SNAP_*`；
> 接线见 `docs/引脚分配与接线.md` 的「摄像头 OV3660」节。
> 画面方向（装云台后的颠倒/镜像）本端不做，将来由 EQ12 端收到照片后后处理。
> `pub/leg` 运动指令解析与串行执行见 `src/workers/move.py` 文件头（含 `sub/leg`
> 完成回执协议：载荷 `done:<指令>`，只回真做完的）；通道/限幅/
> 方向校准在 `src/config.py` 的 `MOVE`，接线见 docs 的「电机与云台（腿）」节。
> `pub/face` 表情指令解析见 `src/workers/screen.py` 文件头；屏参数在
> `src/config.py` 的 `SCREEN`，接线/踩坑（SPI(1)、TTL 口）见 docs 的
> 「1.54 寸屏 ST7789」节。

- 主题名/QoS/方向两端镜像：EQ12 订阅 `sub/*`、发布 `pub/*`；本端反过来。
- **音量衰减在 EQ12 端做**（`eq12_server/src/workers/speak_worker.py` 的 `VOLUME_DIV`），本端只裸播。
- 回声抑制细节：收到 `b'stop'` 时停采并**清空 `pub/speak` 未播缓冲**（对应 eq12 speak_worker 注释建议）。

### 手动验证（只用 mosquitto，不开 EQ12 也能测器官）

```bash
# 腿：连发两条动作 → 订阅 sub/leg 收"每条真做完"的回执
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

## 6. 常见问题速查

| 现象 | 原因 / 解决 |
|---|---|
| 日志反复 `已连接 → 断开 → 已连接` | **同 client_id 互踢**：有第二个实例/客户端在跑。只跑一个实例，`CLIENT_ID` 用唯一值；重启用 `machine.reset()` 杀残留 |
| 改了代码却没生效 | MicroPython import 只在进程内执行一次。**改完要软复位**（`reset`/`machine.reset()`），Ctrl+C 不算 |
| REPL 连上没反应 / "一直有 main" | 根目录 `main.py` 开机自启在跑（REPL 被占）。Ctrl+C 中断；调试期把 `/main.py` 挪走 |
| 开机就卡死 | 多半是 `boot.py` 里 WiFi/NTP 阻塞（NTP 无超时）。用 `boot_debug.py` 覆盖 `/boot.py` 定位 |
| `mpremote: failed to access COM4` | 端口被其它会话占用：先关掉开着的 repl/WebREPL 页面 |
| 串口中文乱码 | 设备输出 UTF-8，终端按 UTF-8 查看即可，属正常 |
| 声音巨响 | 在 EQ12 端调 `VOLUME_DIV`（3=1/8），本端不管 |
| 自问自答（回声） | 音量调小 / 远离喇叭；或检查 pub/ear 指令链路 |
| 上传带上了 `__pycache__` | 上传前先清理 PC 端缓存（见 §3） |

## 7. 测试

**PC 端**（无需设备，验证引擎与全链路逻辑；在 esp32_client/ 下执行）：

```bash
python tests/smoke_mqtt.py     # 假 broker：握手/收发/QoS1 兜底/断线自动重连+重订阅
python tests/smoke_loop.py     # 假 machine+假 camera/jpeg+假 PWM+假 Face+假 broker
                               # （采集上行 → pub/eye 照片 → pub/leg 动作+sub/leg 完成回执 →
                               #   pub/face 表情 → 下行播放 → 停机）
```

**设备端**（最小隔离测试，需已联网且 /src 已上传）：

```bash
mpremote connect COM4 run tests/mqtt_connect_test.py   # 只验 MQTT 连接稳定性（唯一 id，60s）
mpremote connect COM4 run tests/mqtt_pub_storm.py      # 只验持续发布 sub/ear 是否被踢（30s）
```

判据：`连接事件=1` 即 PASS（全程未掉线）。

## 8. 相关文档

- 整项目架构 / 端到端数据流：`../README.md`
- eq12 服务器框架：`../eq12_server/README.md`
- 引脚接线 / 烧录部署 / 命令速查 / 材料清单：`docs/`
