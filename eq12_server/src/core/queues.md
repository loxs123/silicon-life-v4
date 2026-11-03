# 队列接口（queues）

`queues` 是一个**字典**：`{队列名: queue.Queue}`。`Pipeline.__init__(self, queues)`
原样收下，hook 里用 `self.queues[<队列名>]` 读写。

```python
self.queues['tts'].put('你好呀')      # 写
text = self.queues['asr'].get()       # 读
```

## 一、读：`get()` 到什么

| 队列名 | 常量 | 类型 | 内容 / 字段 |
|---|---|---|---|
| `asr` | `QUEUE_ASR` | `str` | 识别出的一句话，如 `'你好呀'`。空文本不入队 |
| `sub/leg` | `QUEUE_LEG_SUB` | `msg` | `msg.payload` = `bytes`，UTF-8 文本 `done:<规范化指令>` |
| `sub/eye` | - | `msg` | `msg.payload` = `bytes`，UTF-8 JSON 照片，见下 |
| `sub/ear` | `QUEUE_EAR_IN` | `msg` | `msg.payload` = `bytes`，裸 PCM **16k/16bit/mono**，640B 一块 |
| `_sub/feishu` | `QUEUE_FEISHU_SUB` | `dict` | 收到的飞书消息，见下 |
| `_sub/desktop` | `QUEUE_DESKTOP_SUB` | `dict` | 桌面结果，见下 |
| `_sub/delay` | `QUEUE_DELAY_SUB` | `dict` | 到点的那条消息，见下 |

### `sub/leg`

```python
'done:forward,50,2'    # 前进 50% 跑满 2 秒、电机已停
'done:pan,90'          # 云台水平已到 90°
'done:right,30,0.5'    # 原地右转 0.5 秒完毕
'done:center'          # 复位完成（云台回中 + 电机停）
```

腿是**串行**的：投一条 `pub/leg` 之后，`sub/leg` 里来的下一条回执就是它做完了。

⚠️ 三个坑：

- `done:` 后面是**解析后的规范化值**——投 `forward,50,2秒`，回执是 `done:forward,50,2`。
  **别按字符串全等比对**，要按解析后的参数比。
- 失败 / 未知指令**不回执** → 等回执**务必设超时**，否则永久挂起。
- 回执在**动作真正做完之后**才发（电机类要跑满时长自动停稳），不是收到指令就回。

### `sub/eye`

```python
{'type': 'photo', 'time': '2025-06-01 12:00:00', 'size': 48213,
 'width': 320, 'height': 240, 'data': '<base64 JPEG>'}
```
`msg.payload` 是 `bytes`，得先 `json.loads`。⚠️ 这里的 `time` 是**字符串**。

### `_sub/feishu`

```python
# 文字消息（没有 type 键）
{'feishu': True, 'text': '你好', 'message_id': 'om_...', 'chat_id': 'oc_...', 'sender': 'ou_...'}

# 图片消息（多了 type 和 image_key；data 是 base64 图片本体）
{'feishu': True, 'type': 'image', 'image_key': 'img_v2_...',
 'data': '<base64 JPEG/PNG>', 'message_id': 'om_...', 'chat_id': 'oc_...', 'sender': 'ou_...'}
```
靠**有没有 `type` 键**区分这两种；其它消息类型不入队。图片收到就按 `image_key` 下载转
base64 放 `data`（下载失败时没有 `data`）。完整格式见 `core/hooks/protocols/queue.xml`。

### `_sub/desktop`

```python
# 截图本体
{'type': 'screen', 'time': <unix秒>, 'size': <JPEG字节数>,
 'width': W, 'height': H, 'fmt': 'jpeg', 'data': '<base64 JPEG>'}

# 指令完成回执；command 是原样回传的那条指令
{'type': 'done', 'time': <unix秒>, 'command': <原始指令 dict>}
```
用 `type` 区分两类。**两种载荷谁先谁后不保证，别依赖顺序。**
指令无效或执行失败**只打日志、不回执** → 等回执必须设超时。

### `_sub/delay`

```python
# 到点推的这一条
{'text': '15 分钟之前你让我提醒我喝水，现在到点了，你来接着办。',
 'in': 900.0, 'due_at': <unix秒>, 'fired_at': <unix秒>}
```

`text` 就是那句话（模板 `config.DELAY_ECHO_TEMPLATE`，占位符 `{ago}` `{text}`）。
⚠️ 目前**没有下游消费者**：DelayWorker 只负责把它推进来，谁读 `_sub/delay` 谁决定
下一步（说 / 做 / 转发都行），它不碰 asr / tts 等任何别的队列。

---

## 二、写：`put()` 什么

| 想干什么 | 队列名 | 常量 | 类型 | 投什么 |
|---|---|---|---|---|
| 让嘴说话 | `tts` | `QUEUE_TTS` | `str` | `'你好呀'`（空串被跳过） |
| 让腿动 | `pub/leg` | `QUEUE_LEG_PUB` | `str` | `'forward,50,2'` |
| 让脸变表情 | `pub/face` | - | `str` | `'happy'` |
| 拍一张照 | `pub/eye` | - | `bytes` | `b'photo'` |
| 耳朵停采 / 恢复 | `pub/ear` | `QUEUE_EAR_CTRL` | `bytes` | `b'stop'` / `b'start'` |
| 发下行语音 | `pub/speak` | `QUEUE_SPEAK_OUT` | `bytes` | 裸 PCM **24k/16bit/mono** |
| 让这台电脑动 | `_pub/desktop` | `QUEUE_DESKTOP_PUB` | `dict` | 见下 |
| 发飞书 | `_pub/feishu` | `QUEUE_FEISHU_PUB` | `dict` | 见下 |
| 延迟消息（到点再叫我） | `_pub/delay` | `QUEUE_DELAY_PUB` | `dict` | 见下 |
| （占位） | `pub/brain` `pub/mouth` | — | — | 格式未定义 |

### `tts`

```python
'你好呀'    # 一句要说的文本；空串被跳过
```

### `pub/leg`

```python
'forward,50,2'    # 前进 50%，跑 2 秒（缺省时长 1.5s）
'back,40'         # 后退 40%（缺省时长 1.5s）
'left,30'         # 原地左转 30%（缺省时长 1.0s）
'right,30,0.5'    # 原地右转 0.5 秒（⚠️ 缺省时长未标注）
'pan,90'          # 云台水平，限幅 60~120
'tilt,45'         # 云台俯仰，限幅 45~135
'stop'            # 电机立即停
'center'          # 云台回中 + 电机停
```

都是 UTF-8 文本 `动词[,参数[,参数]]`；时长 4 种写法都行：`3` / `1.5s` / `800ms` / `2秒`。

### `pub/face`

```python
'idle'      # 待机
'listen'    # 聆听
'think'     # 思考
'speak'     # 说话
'happy'     # 开心
'sleep'     # 睡觉
```

都是 UTF-8 文本，大小写不敏感，可带旧前缀 `[SCR]:`；别名 `neutral` → `idle`。

### `pub/eye`

```python
b'photo'    # 拍一张 → 照片异步从 sub/eye 上来
```

### `pub/ear`

```python
b'stop'     # 停采 + 清掉未播缓冲
b'start'    # 恢复采集
```

回声抑制用。**平时由 SpeakWorker 自动管理**（出声前 stop、句毕 start），
hook 一般不用碰——手动发会打断它的配对。

### `_pub/desktop`

```python
{'type': 'keyboard', 'value': 'A'}                         # 按下再抬起，'time' 给保持秒数，缺省 0.05
{'type': 'keyboard', 'value': 'CTRLALTDELETE'}             # 组合键直接拼写
{'type': 'mouse', 'direction': 'UP', 'value': 12}          # 相对移动，direction: UP/DOWN/LEFT/RIGHT
{'type': 'scroll', 'direction': 'DOWN', 'value': 5}        # 滚轮，direction: UP/DOWN
{'type': 'screenshot'}                                     # → 结果进 _sub/desktop
{'type': 'clipboard', 'value': '要写进剪切板的文字'}        # 写剪切板（空串 = 清空）
```

剪切板配合键盘就能粘贴到别处：先 `clipboard` 写入，再
`{'type':'keyboard','value':'CTRLV'}`。

按键串按**最长匹配**切分（`LEFT` 是方向键，不是 L+E+F+T）；大小写靠显式 `SHIFT`
（`SHIFTA` = 大写 A）。特殊键用大写规范名：`ENTER` `SPACE` `TAB` `ESC` `BACKSPACE`
`DELETE` `HOME` `END` `PAGEUP` `PAGEDOWN` `LEFT` `RIGHT` `UP` `DOWN` `CTRL` `ALT`
`SHIFT` `WIN` `F1`~`F24`，完整清单见 `workers/desktop_worker.py` 的 `_KEY_ALIAS`。

### `_pub/feishu`

```python
# 发一条文字 —— 不传 chat_id，自动回到「消息来的那个会话」
{'text': '你好'}

# 发一张图 —— 同上
{'img': '<base64 JPEG>'}

# 只有要发给「别的会话」时才需要显式指定
{'text': '你好', 'chat_id': 'oc_别的会话'}
```

### `_pub/delay`

```python
{'text': '提醒我喝水', 'in': 900}    # 900 秒后到点 —— 投递只有这一种格式
```

「15 分钟」写 `900`（自己乘好）。格式固定、**不做校验**：少键或类型不对会在
DelayWorker 线程里直接抛异常，不会有错误回执。**不阻塞**：投完立刻返回，别自己
`sleep` 等 —— 睡的是 hook 和 brain 主循环。DelayWorker 每 `DELAY_POLL_S`（默认 1 秒）
轮询一次队列与到期，所以到点精度是 ±`DELAY_POLL_S`。

```python
# 典型用法（brain hook 里）
self.queues['_pub/delay'].put({'text': '提醒我喝水', 'in': 15 * 60})
print('[brain] remind → _pub/delay: 提醒我喝水 in 900s', flush=True)
```
