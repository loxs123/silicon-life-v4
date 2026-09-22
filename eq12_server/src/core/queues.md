# 队列清单与载荷格式

队列共 **19 个**，全部在 `src/main_loop.py` 的 `__init__` 里创建（第 35–49 行），
以 `queues['<名字>']` 访问。**QoS 全部为 0。**

## 通用规则

| 规则 | 说明 |
|---|---|
| 方向 | `sub/*` = 器官 → 服务器（服务器订阅）；`pub/*` = 服务器 → 器官（服务器发布）|
| `sub/*` 载荷 | 入队的是**整个 paho `MQTTMessage` 对象**，业务数据在 `.payload`（`main_loop.py:148`）|
| `pub/*` 载荷 | 入队的是**原始 `bytes`**，专职发送线程直接 `publish`，不做任何编码包装 |
| `_` 前缀 | 纯内部队列（飞书/桌面），不是 MQTT 主题，发送线程和 `_STOP` 都不会碰 |
| 停机哨兵 | `_STOP` **只投 `pub/*` 和 `sub/*`**（`main_loop.py:109-111`）。`asr`/`tts`/`_*` 不投，阻塞在上面的 worker 只能靠 daemon 线程随进程退出 |

---

# 一、MQTT 上行 `sub/*`

服务器订阅，ESP32 发布。**当前全部没有消费者**（brain 待接）。

## `sub/ear` —— 麦克风音频
**投** ESP32 `EarWorker`　**取** `EarWorker`（已接）
**载荷** `.payload` = 16k / 16bit / mono **裸 PCM**，640B 一块（20ms）

dashscope 流式 ASR 的固定输入格式。无枚举，纯音频流。

## `sub/eye` —— 照片
**投** ESP32 `CameraWorker`　**取** 无人（brain 待接）
**载荷** `.payload` = UTF-8 JSON，**可整体 `json.loads`**（单条消息一张图，不是视频流）

| 字段 | 类型 | 说明 |
|---|---|---|
| `type` | `str` | 固定 `"photo"`（唯一枚举值）|
| `time` | `str` | **字符串**，`"2025-06-01 12:00:00"` |
| `size` | `int` | JPEG 字节数 |
| `width` / `height` | `int` | 320 / 240（`config.CAM_W`/`CAM_H`，QVGA）|
| `data` | `str` | base64 JPEG，`b64decode` 后即 JPEG 文件字节 |

```json
{"type":"photo","time":"2025-06-01 12:00:00","size":48213,
 "width":320,"height":240,"data":"<base64 JPEG>"}
```

> 注意**没有** `fmt` 字段（与 `_sub/desktop` 的截图不同）。

## `sub/leg` —— 动作完成回执
**投** ESP32 `MoveWorker`　**取** 无人（brain 待接）
**载荷** `.payload` = UTF-8 文本，`done:<规范化指令>`

前缀 `done:` 固定。腿**真做完**一条 `pub/leg` 才回执一条（失败/未知指令不回执）：

```text
done:forward,50,2      # 前进 50% 已跑满 2 秒、电机已自动停
done:pan,90            # 云台水平已转到 90°
done:tilt,45           # 云台俯仰已转到 45°
done:right,30,0.5      # 原地右转 0.5 秒完毕
done:center            # 复位完成（云台回中 + 电机停）
done:stop              # 已停
```

用途：`pub/leg` 指令 → `sub/leg` 回执配对，知道动作**做完了**，可驱动动作序列下一步。

## `sub/brain` —— ⚠️ 未定义
服务器订阅了这个主题，但**既没有生产者也没有消费者**，载荷格式未约定。

## `sub/mouth` —— ⚠️ 未定义
同上。服务器订阅了但两端都没接。

## `sub/face` —— ⚠️ 未定义
服务器订阅了，但 ESP32 端 `PUB_TOPICS` 只有 `sub/ear`/`sub/eye`/`sub/leg`，
**从不发布此主题**。

---

# 二、MQTT 下行 `pub/*`

服务器发布，ESP32 订阅。每个主题一个专职发送线程串行发送。

## `pub/speak` —— TTS 语音流
**投** `SpeakWorker`（`speak_worker.py:137`）　**取** 发送线程 → MQTT → ESP32 `SpeakWorker` → I2S 喇叭
**载荷** 24k / 16bit / mono **裸 PCM** `bytes`

- **不是**上行 `sub/ear` 的 16k，两端速率不同
- 每样本右移 `VOLUME_DIV=4` 位 = **1/16 音量（-24dB）**，ESP32 端只做裸播放
- 一句 TTS 会被切成多段 PCM 陆续投递（`response.audio.delta` 事件逐段转发）

## `pub/ear` —— 采集启停指令
**投** `SpeakWorker`（`speak_worker.py:298`、`:311`）　**取** 发送线程 → ESP32 `EarWorker`
**载荷** `bytes`，枚举 **2 个值**：

| 载荷 | 含义 |
|---|---|
| `b'stop'` | 停采。TTS 出声前发，防 mic 收到自己的声音 |
| `b'start'` | 恢复采集。整句处理完（成功/失败/重连）后发，`try/finally` 保证任何路径都发 |

## `pub/eye` —— 拍照指令
**投** 暂无（brain 待接）　**取** 发送线程 → ESP32 `CameraWorker`
**载荷** `bytes`，枚举 **1 个值**：

| 载荷 | 含义 |
|---|---|
| `b'photo'` | 拍一张 → 编码 → 上行 `sub/eye`。其它任何载荷都被忽略并打日志 |

按需拍照，一指令一图。

## `pub/leg` —— 运动指令
**投** 暂无（brain 待接）　**取** 发送线程 → ESP32 `MoveWorker`（**串行执行**，一条做完才做下一条）
**载荷** UTF-8 文本 `bytes`

**文法**：`动词[,参数1[,参数2]]`。兼容旧前缀 `[MOVE]:` 与空格分隔（`forward 50 2`）。

| 动词 | 参数 | 说明 |
|---|---|---|
| `forward` | 速度百分比, [时长] | 前进。缺省时长 **1.5s** |
| `back` | 速度百分比, [时长] | 后退。缺省时长 **1.5s** |
| `left` | 速度百分比, [时长] | 原地左转。缺省时长 **1.0s** |
| `right` | 速度百分比, [时长] | 原地右转。缺省时长 **1.0s** |
| `pan` | 角度 | 云台水平，机械限幅 **60~120** |
| `tilt` | 角度 | 云台俯仰，机械限幅 **45~135** |
| `stop` | — | 电机立即停止 |
| `center` | — | 云台回中(90/90) + 电机停 |

**时长的 4 种写法**：`3` / `1.5s` / `800ms` / `2秒`。

```text
forward,50,2      # 前进 50%，跑 2 秒自动停
back,40           # 后退 40%（默认 1.5s）
left,30           # 原地左转 30%（默认 1.0s）
right,30,0.5      # 原地右转 0.5 秒
pan,90            # 云台水平转 90°
tilt,45           # 云台俯仰转 45°
stop              # 电机停
center            # 回中
```

## `pub/face` —— 表情指令
**投** 暂无（brain 待接）　**取** 发送线程 → ESP32 `ScreenWorker`（**串行**，一条画完才切下一条）
**载荷** UTF-8 文本 `bytes`，枚举 **6 个状态 + 1 个别名**：

| 值 | 效果 |
|---|---|
| `idle` | 待机（微笑）|
| `listen` | 聆听（眼睛下移 O 嘴）|
| `think` | 思考（眼球上瞟）|
| `speak` | 说话（嘴部开合动画，持续到下一条指令）|
| `happy` | 开心（咧嘴）|
| `sleep` | 睡觉（闭眼 zzz）|
| `neutral` | 别名，等价于 `idle` |

大小写不敏感、可带空格、可带旧前缀 `[SCR]:`（如 `[SCR]:happy`）。
眨眼动画只发生在睁眼状态（`idle`/`listen`/`think`/`happy`）。

## `pub/brain` —— ⚠️ 未定义
有发送线程和 MQTT 主题，但**没有任何投递方**，载荷格式未约定。

## `pub/mouth` —— ⚠️ 未定义
同上，无投递方。

---

# 三、内部流水线

不经 MQTT，进程内队列。**不吃 `_STOP` 哨兵。**

## `asr` —— 语音识别结果
**投** `EarWorker`（`ear_worker.py:46`）　**取** brain（待接）
**载荷** `str`，一句识别文本

由 dashscope ASR 回调在 `sentence['sentence_end']` 为真时投递，即**一句话一条**，
不是逐字流。空文本不投。

## `tts` —— 待合成文本
**投** brain（待接）　**取** `SpeakWorker`（`speak_worker.py:186`）
**载荷** `str`，一句要说的文本

**空串会被跳过**（`if not text: continue`），所以投空串是安全的无操作。

---

# 四、内部工具队列

`_` 前缀，进程内直连外部世界（飞书 OpenAPI / 本机键鼠），不经 MQTT。

## `_sub/feishu` —— 收到的飞书消息
**投** `FeishuWorker`（`feishu_worker.py:186`、`:199`）　**取** brain（待接）
**载荷** `dict`，按消息类型分**两种**（靠有无 `type` 字段区分）：

**① 文字消息**（无 `type` 字段）：

```python
{'feishu': True, 'text': '你好', 'message_id': 'om_...',
 'chat_id': 'oc_...', 'sender': '<发送者昵称>'}
```

**② 图片消息**（`type` = `'image'`）：

```python
{'feishu': True, 'type': 'image', 'image_key': 'img_v2_...',
 'message_id': 'om_...', 'chat_id': 'oc_...', 'sender': '<发送者昵称>'}
```

| 字段 | 说明 |
|---|---|
| `feishu` | 固定 `True`，标识来源 |
| `sender` | **昵称字符串**（不是 open_id）|
| `image_key` | 飞书图片 key，要拿图需另调 API 下载 |
| 其它消息类型 | 只打日志、不入队 |

## `_pub/feishu` —— 要发出的飞书消息
**投** brain（待接）　**取** `FeishuWorker._send_out`（`feishu_worker.py:211`）
**载荷** **两种形态**，靠类型区分：

**① `str`，前缀 `[FEISHU]:`** —— 在指定消息下回复文字：

```python
'[FEISHU]:<message_id>|<回复文字>'
# message_id 与文字都用 | 分隔，两者任一为空则忽略整条
```

**② `dict`，键 `img`** —— 给会话主动发图：

```python
{'img': '<base64 JPEG>', 'chat_id': 'oc_...'}
# chat_id 可省略 → 用最近一次收到消息的会话
# 无 img 键的 dict、以及非上述形态的载荷 → 打日志忽略
```

## `_pub/desktop` —— 桌面控制指令
**投** brain（待接）　**取** `DesktopWorker`（`desktop_worker.py:189`）
**载荷** `dict`，必带 `type`，枚举 **4 个值**：

| `type` | 其它字段 | 说明 |
|---|---|---|
| `keyboard` | `value` 按键串，`time` 保持秒数（缺省 `0.05`）| 同时按下 `value` 全部键并保持 `time` 秒 |
| `mouse` | `direction`，`value` 像素数 | 鼠标相对移动 |
| `scroll` | `direction`，`value` 格数 | 滚轮滚动 |
| `screenshot` | 无 | 截全屏 JPEG → 投 `_sub/desktop` |

**`direction` 枚举**：`mouse` 为 `UP` / `DOWN` / `LEFT` / `RIGHT`（映射 `_MOUSE_STEP`）；
`scroll` 只有 `UP` / `DOWN`（`UP` → pyautogui 正数）。方向非法或 `value` 为 0 → 指令无效、不回执。

**`keyboard` 的 `value` 按键串**按**最长匹配**切分（`split_keys`），所以 `LEFT` 是方向键
而不是 `L`+`E`+`F`+`T`。可用的特殊键名（大写规范名，别名用 `/` 分隔）：

| 键名 | |
|---|---|
| `ENTER` / `RETURN` | `SPACE` |
| `TAB` | `ESC` / `ESCAPE` |
| `BACKSPACE` | `DELETE` |
| `INSERT` | `HOME` |
| `END` | `PAGEUP` / `PGUP` |
| `PAGEDOWN` / `PGDN` | `LEFT` / `RIGHT` / `UP` / `DOWN` |
| `CTRL` / `CONTROL` | `ALT` |
| `SHIFT` | `WIN` / `META` / `CMD` / `COMMAND` |
| `CAPSLOCK` / `CAPS` | `NUMLOCK` |
| `SCROLLLOCK` | `PRINTSCREEN` / `PRTSC` |
| `PAUSE` | `BREAK` |

此外还有 **`F1`~`F24`**（`_FKEY_RE`），以及任意**单字符**（字母/数字/标点，`key_name` 兜底）。

```python
{"type": "keyboard", "value": "AZ"}            # A+Z 同按
{"type": "keyboard", "value": "CTRLALTDELETE"} # Ctrl+Alt+Delete
{"type": "keyboard", "value": "SHIFTA"}        # 大写 A（大小写靠显式 SHIFT）
{"type": "mouse",   "direction": "UP",  "value": 12}
{"type": "scroll",  "direction": "DOWN", "value": 5}
{"type": "screenshot"}
```

## `_sub/desktop` —— 截图与完成回执
**投** `DesktopWorker`（`desktop_worker.py:307`、`:326`）　**取** brain（待接）
**载荷** `dict`，按 `type` 分**两种**，**同一个队列、按序排列**：

**① 截图**（`type` = `'screen'`）：

| 字段 | 类型 | 说明 |
|---|---|---|
| `type` | `str` | 固定 `"screen"` |
| `time` | `int` | **unix 秒**（区别于 `sub/eye` 的时间字符串）|
| `size` | `int` | JPEG 字节数 |
| `width` / `height` | `int` | 屏幕分辨率 |
| `fmt` | `str` | 固定 `"jpeg"`（`sub/eye` 没有这个字段）|
| `data` | `str` | base64 JPEG，质量 `JPEG_QUALITY=85` |

```python
{'type': 'screen', 'time': 1748764800, 'size': 312044,
 'width': 1920, 'height': 1080, 'fmt': 'jpeg', 'data': '<base64 JPEG>'}
```

**② 完成回执**（`type` = `'done'`）：

```python
{'type': 'done', 'time': <unix秒>, 'command': <原始指令 dict>}
```

- `command` 是**原样回传**的 `_pub/desktop` 指令 dict，用于配对"哪条做完了"
- **每条指令真执行成功**后才追加一条：keyboard 已按完抬起 / mouse 已移动 /
  scroll 已滚 / screenshot 已把截图入队（紧随其后的 `{'type':'screen'}` 即结果）
- 指令无效（缺参/方向错/无按键）或执行抛异常 → **只打日志、不回执**

---

# 五、两条最容易踩的规则

1. **`sub/*` 队列里是 `MQTTMessage`，不是文本。** 必须 `.payload` 才拿到业务数据。
   `asr` / `tts` / `_sub/*` / `_pub/*` 里才是裸 `str` / `bytes` / `dict`。

2. **时间字段类型不统一**：`sub/eye` 的 `time` 是字符串 `"2025-06-01 12:00:00"`，
   `_sub/desktop` 的 `time` 是 unix 整数。跨队列复用代码时容易在这里出错。

> 另外：`config.py` 的 `SUB_TOPICS` 里有 `sub/leg`，ESP32 也确实在发完成回执，
> 但服务器端**没有消费者**（`queues['sub/leg']` 全项目零引用），所以目前收不到
> "动作做完了没"。
