# 队列接口（queues）

`queues` 是一个**字典**：`{队列名: queue.Queue}`。`Pipeline.__init__(self, queues)`
原样收下，hook 里用 `self.queues[<队列名>]` 读写。

```python
self.queues['tts'].put('你好呀')      # 写
text = self.queues['asr'].get()       # 读
```

**队列不做任何包装、不解析：put 什么，get 到什么。**

---

## 三条规则

1. **队列名优先用 `config.py` 的常量**（`QUEUE_TTS`、`QUEUE_LEG_PUB`…），别写字面量。
   ⚠️ 但 `config.py` 里**没有** `sub/eye`、`pub/eye`、`pub/face` 的常量，
   这三处现在只能用字面量——建议补上，否则表里会混着两种写法。
2. ⚠️ **`pub/*` 与 `sub/*` 是 MQTT 主题队列**，`get()` 到的是 paho **消息对象**，
   业务数据在 `msg.payload` 里，类型是 `bytes`。**内部队列（`asr`/`tts`/`_*`）没有这一层包装。**
   这是最容易踩的坑。
3. 载荷只有 **四种类型**：`str`、`bytes`、`dict`、`msg`。没有第五种。

---

## 一、读：`get()` 到什么

| 队列名 | 常量 | 类型 | 内容 / 字段 |
|---|---|---|---|
| `asr` | `QUEUE_ASR` | `str` | 识别出的一句话，如 `'你好呀'`。空文本不入队 |
| `tts` | `QUEUE_TTS` | `str` | *(不作为读入口，见写表)* |
| `sub/leg` | `QUEUE_LEG_SUB` | `msg` | `msg.payload` = `bytes`，UTF-8 文本 `done:<规范化指令>` |
| `sub/eye` | ⚠️ 无 | `msg` | `msg.payload` = `bytes`，UTF-8 JSON 照片，见下 |
| `sub/ear` | `QUEUE_EAR_IN` | `msg` | `msg.payload` = `bytes`，裸 PCM **16k/16bit/mono**，640B 一块 |
| `_sub/feishu` | `QUEUE_FEISHU_SUB` | `dict` | 收到的飞书消息，见下 |
| `_sub/desktop` | `QUEUE_DESKTOP_SUB` | `dict` | 桌面结果，见下 |
| `sub/brain` `sub/mouth` `sub/face` | — | — | 占位，格式未定义 |

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

# 图片消息（多了 type 和 image_key）
{'feishu': True, 'type': 'image', 'image_key': 'img_v2_...',
 'message_id': 'om_...', 'chat_id': 'oc_...', 'sender': 'ou_...'}
```
靠**有没有 `type` 键**区分这两种；其它消息类型不入队。

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

---

## 二、写：`put()` 什么

| 想干什么 | 队列名 | 常量 | 类型 | 投什么 |
|---|---|---|---|---|
| 让嘴说话 | `tts` | `QUEUE_TTS` | `str` | `'你好呀'`（空串被跳过） |
| 让腿动 | `pub/leg` | `QUEUE_LEG_PUB` | `str` | `'forward,50,2'` |
| 让脸变表情 | `pub/face` | ⚠️ 无 | `str` | `'happy'` |
| 拍一张照 | `pub/eye` | ⚠️ 无 | `bytes` | `b'photo'` |
| 耳朵停采 / 恢复 | `pub/ear` | `QUEUE_EAR_CTRL` | `bytes` | `b'stop'` / `b'start'` |
| 发下行语音 | `pub/speak` | `QUEUE_SPEAK_OUT` | `bytes` | 裸 PCM **24k/16bit/mono** |
| 让这台电脑动 | `_pub/desktop` | `QUEUE_DESKTOP_PUB` | `dict` | 见下 |
| 发飞书 | `_pub/feishu` | `QUEUE_FEISHU_PUB` | `dict` | 见下 |
| `pub/brain` `pub/mouth` | — | — | — | 占位，格式未定义 |

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

### `_pub/desktop`

```python
{'type': 'keyboard', 'value': 'A'}                        # 按下再抬起，'time' 给保持秒数，缺省 0.05
{'type': 'keyboard', 'value': 'CTRLALTDELETE'}             # 组合键直接拼写
{'type': 'mouse', 'direction': 'UP', 'value': 12}          # 相对移动，direction: UP/DOWN/LEFT/RIGHT
{'type': 'scroll', 'direction': 'DOWN', 'value': 5}        # 滚轮，direction: UP/DOWN
{'type': 'screenshot'}                                     # → 结果进 _sub/desktop
```

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

两种都是 dict，都走 `im.v1.message.create`（**主动发新消息**，不引用任何历史消息），
所以**不需要 `message_id`**。

**`chat_id` 通常不用传**，解析顺序是：

1. 载荷里的 `chat_id`
2. 最近一次收到消息的会话 —— 从哪来的，回哪去
3. `config.FEISHU_DEFAULT_CHAT_ID` —— 进程刚重启、还没人说话时的兜底

三者都为空 → 打日志放弃发送。

其它行为：

- 既没有 `text` 也没有 `img` → 打日志忽略
- 发送失败**只打日志、不回队列** → 上游无法知道送达与否

## 
