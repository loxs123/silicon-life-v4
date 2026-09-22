# 队列与载荷

写 core hook 只需要认这个文件：你往 `self.queues['<队列名>']` 里 **put 的就是载荷本身**，
`get()` 出来的也是载荷本身。下面按来源分四组：飞书、桌面、内部流水线、MQTT 主题队列。

---

# 一、飞书（本机进程内）

## `_sub/feishu` —— 收到的飞书消息
**投** FeishuWorker　**取** hook

```python
# 文字消息（没有 type 字段）
{'feishu': True, 'text': '你好', 'message_id': 'om_...', 'chat_id': 'oc_...', 'sender': 'ou_...'}

# 图片消息（有 type 字段）
{'feishu': True, 'type': 'image', 'image_key': 'img_v2_...',
 'message_id': 'om_...', 'chat_id': 'oc_...', 'sender': 'ou_...'}
```

靠有没有 `type` 区分这两种；其它消息类型不会入队。

## `_pub/feishu` —— 要发出去的飞书消息
**投** hook　**取** FeishuWorker

| 想做什么 | 投什么 |
|---|---|
| 在收到的某条消息下回复文字 | 字符串 `'[FEISHU]:<message_id>\|<文字>'` |
| 给会话发一张图 | `{'img': '<base64 JPEG>', 'chat_id': 'oc_...'}` |

- 文字回复里 `message_id` 和文字任一为空 → 整条忽略；文字里带 `|` 没问题（只按第一个 `|` 切）
- 发图的 `chat_id` 可以省略，省略时发给最近一次收到消息的会话

---

# 二、桌面（本机进程内）

## `_pub/desktop` —— 让这台电脑动一下
**投** hook　**取** DesktopWorker（一条做完才做下一条）

| 载荷 | 效果 |
|---|---|
| `{'type': 'keyboard', 'value': 'A'}` | 同时按下 `value` 里的键再全部抬起；`'time'` 给保持秒数，缺省 0.05 |
| `{'type': 'keyboard', 'value': 'CTRLALTDELETE'}` | 组合键直接拼写（按最长匹配切分，所以 `LEFT` 是方向键而不是 L+E+F+T）|
| `{'type': 'mouse', 'direction': 'UP', 'value': 12}` | 鼠标相对移动，`direction` 只能 `UP`/`DOWN`/`LEFT`/`RIGHT` |
| `{'type': 'scroll', 'direction': 'DOWN', 'value': 5}` | 滚轮滚动，`direction` 只能 `UP`/`DOWN` |
| `{'type': 'screenshot'}` | 截一张全屏 JPEG → 进 `_sub/desktop` |

`keyboard` 的 `value`：单字符（字母/数字/标点）直接写，大小写靠显式 `SHIFT`（`SHIFTA` = 大写 A）；
特殊键用大写规范名 —— `ENTER` `SPACE` `TAB` `ESC` `BACKSPACE` `DELETE` `HOME` `END`
`PAGEUP` `PAGEDOWN` `LEFT` `RIGHT` `UP` `DOWN` `CTRL` `ALT` `SHIFT` `WIN` `F1`~`F24` 等，
完整清单见 `workers/desktop_worker.py` 的 `_KEY_ALIAS`。

## `_sub/desktop` —— 桌面的结果
**投** DesktopWorker　**取** hook

```python
# 截图本体
{'type': 'screen', 'time': <unix秒>, 'size': <JPEG字节数>,
 'width': W, 'height': H, 'fmt': 'jpeg', 'data': '<base64 JPEG>'}

# 指令完成回执；command 就是原样回传的那条指令
{'type': 'done', 'time': <unix秒>, 'command': <原始指令 dict>}
```

- 指令无效（方向错、值为 0、没按键…）或执行失败：只打日志，**不回执**
- 两种载荷谁先谁后不保证，写 hook 时别依赖顺序

---

# 三、内部流水线

| 队列 | 投 | 取 | 载荷 |
|---|---|---|---|
| `asr` | 耳朵（识别出一句话）| hook | `str`，一句文本；空文本不入队 |
| `tts` | hook | 嘴（合成语音）| `str`，要说的一句文本；空串会被跳过 |

---

# 四、MQTT 主题队列

`sub/*` 是入站（器官 → 服务器），`pub/*` 是出站（服务器 → 器官）。
从这两类队列 `get()` 到的是消息对象，业务数据在 `msg.payload` 里。

| 队列 | 载荷 |
|---|---|
| `sub/ear` | `bytes`，原始音频：16k / 16bit / 单声道 PCM，640B 一块 |
| `sub/eye` | `bytes`，UTF-8 JSON：`{'type': 'photo', 'time': '2025-06-01 12:00:00', 'size': 48213, 'width': 320, 'height': 240, 'data': '<base64 JPEG>'}` |
| `sub/leg` | `bytes`，文本 `done:<规范化指令>`，如 `done:forward,50,2`、`done:center` |
| `pub/speak` | `bytes`，24k / 16bit / 单声道 PCM |
| `pub/ear` | `bytes`，只有两个值：`b'stop'`（停采）/ `b'start'`（恢复采集）|
| `pub/eye` | `bytes`，只有一个值：`b'photo'` |
| `pub/leg` | `bytes`，文本 `动词[,参数[,参数]]`，见下表 |
| `pub/face` | `bytes`，文本，6 个状态 + 1 个别名：`idle` / `listen` / `think` / `speak` / `happy` / `sleep` / `neutral`(=idle) |
| `sub/brain`、`sub/mouth`、`sub/face`、`pub/brain`、`pub/mouth` | 载荷格式未定义 |

**`pub/leg` 的动词**（缺省时长：前进/后退 1.5s，左转/右转 1.0s）：

| 动词 | 参数 | 说明 |
|---|---|---|
| `forward` / `back` | 速度百分比, [时长] | 前进 / 后退 |
| `left` / `right` | 速度百分比, [时长] | 原地左转 / 右转 |
| `pan` | 角度 | 云台水平，机械限幅 60~120 |
| `tilt` | 角度 | 云台俯仰，机械限幅 45~135 |
| `stop` / `center` | — | 电机停 / 云台回中 |

时长的 4 种写法：`3` / `1.5s` / `800ms` / `2秒`。

**投 `pub/leg` 之后怎么知道做完了**：读 `sub/leg` 的下一条 `done:<规范化指令>`。
腿是串行执行的（一条做完才做下一条），所以"投一条 → 等下一条回执"就是自己那条；
但 `done:` 后面是**解析后的规范化值** —— 投 `forward,50,2秒`，回执是 `done:forward,50,2`，
所以别按字符串全等比对。另外失败/未知指令**不回执**，等回执时务必设超时。
