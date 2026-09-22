# 队列与载荷

写 core hook 只需要认这个文件：你往 `self.queues['<队列名>']` 里 **put 的就是载荷本身**，
`get()` 出来的也是载荷本身。

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

```python
# 在收到的某条消息下回复文字
'[FEISHU]:<message_id>|<文字>'

# 给会话发一张图
{'img': '<base64 JPEG>', 'chat_id': 'oc_...'}
```

`message_id` 和文字任一为空 → 整条忽略；文字里带 `|` 没问题（只按第一个 `|` 切）。
发图的 `chat_id` 可以省略，省略时发给最近一次收到消息的会话。

---

# 二、桌面（本机进程内）

## `_pub/desktop` —— 让这台电脑动一下
**投** hook　**取** DesktopWorker（一条做完才做下一条）

```python
# 按下再抬起；'time' 给保持秒数，缺省 0.05
{'type': 'keyboard', 'value': 'A'}

# 组合键直接拼写
{'type': 'keyboard', 'value': 'CTRLALTDELETE'}

# 相对移动；direction: UP / DOWN / LEFT / RIGHT
{'type': 'mouse', 'direction': 'UP', 'value': 12}

# 滚轮；direction: UP / DOWN
{'type': 'scroll', 'direction': 'DOWN', 'value': 5}

# 截图 → 进 _sub/desktop
{'type': 'screenshot'}
```

按键串按**最长匹配**切分，所以 `LEFT` 是方向键（不是 L+E+F+T）；大小写靠显式 `SHIFT`
（`SHIFTA` = 大写 A）。特殊键用大写规范名：`ENTER` `SPACE` `TAB` `ESC` `BACKSPACE` `DELETE`
`HOME` `END` `PAGEUP` `PAGEDOWN` `LEFT` `RIGHT` `UP` `DOWN` `CTRL` `ALT` `SHIFT` `WIN` `F1`~`F24`，
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

指令无效（方向错 / 值为 0 / 没按键…）或执行失败：只打日志，**不回执**。
两种载荷谁先谁后不保证，写 hook 时别依赖顺序。

---

# 三、内部流水线

## `asr` —— 耳朵识别出的一句话
**投** 耳朵　**取** hook

```python
# 一句识别文本
'你好呀'
```

空文本不入队。

## `tts` —— 要让嘴说出来的一句
**投** hook　**取** 嘴

```python
# 一句要说的文本
'你好呀'
```

空串会被跳过。

---

# 四、MQTT 主题队列

`sub/*` 是入站（器官 → 服务器），`pub/*` 是出站（服务器 → 器官）。
这两类队列 `get()` 到的是消息对象，**业务数据在 `msg.payload` 里，都是 `bytes`** ——
下面每条标的就是 `msg.payload` 的内容。

## `sub/ear` —— 耳朵的原始音频
**投** 耳朵　**取** hook

```python
# 原始音频：16k / 16bit / 单声道 PCM，640B 一块
bytes
```

## `sub/eye` —— 眼拍的一张照片
**投** 眼　**取** hook

```python
# 一张照片（UTF-8 JSON）
{'type': 'photo', 'time': '2025-06-01 12:00:00', 'size': 48213,
 'width': 320, 'height': 240, 'data': '<base64 JPEG>'}
```

`time` 是字符串；`_sub/desktop` 的 `time` 是 unix 秒，两边的类型不一样。

## `sub/leg` —— 腿的动作完成回执
**投** 腿　**取** hook

```python
# 前进 50% 跑满 2 秒、电机已停
'done:forward,50,2'

# 云台水平已到 90°
'done:pan,90'

# 原地右转 0.5 秒完毕
'done:right,30,0.5'

# 复位完成（云台回中 + 电机停）
'done:center'
```

都是 `done:<规范化指令>`。腿**串行**执行：投一条 `pub/leg` 之后，`sub/leg` 里来的下一条回执
就是它做完了。但 `done:` 后面是**解析后的规范化值** —— 投 `forward,50,2秒`，回执是
`done:forward,50,2`，所以别按字符串全等比对；失败 / 未知指令**不回执**，等回执时务必设超时。

## `pub/speak` —— 下行语音流
**投** 嘴　**取** 扬声器

```python
# 一段 PCM 语音：24k / 16bit / 单声道
bytes
```

## `pub/ear` —— 耳朵采集启停
**投** 嘴　**取** 耳朵

```python
# 停采：出声前发，防 mic 收到自己的声音
b'stop'

# 恢复采集：整句处理完发
b'start'
```

## `pub/eye` —— 拍一张
**投** hook　**取** 眼

```python
# 拍一张 → 照片从 sub/eye 上来
b'photo'
```

## `pub/leg` —— 运动指令
**投** hook　**取** 腿

```python
# 前进 50%，跑 2 秒（缺省时长 1.5s）
'forward,50,2'

# 后退 40%（缺省时长 1.5s）
'back,40'

# 原地左转 30%（缺省时长 1.0s）
'left,30'

# 原地右转 0.5 秒
'right,30,0.5'

# 云台水平，限幅 60~120
'pan,90'

# 云台俯仰，限幅 45~135
'tilt,45'

# 电机立即停
'stop'

# 云台回中 + 电机停
'center'
```

都是 UTF-8 文本 `动词[,参数[,参数]]`，时长的 4 种写法：`3` / `1.5s` / `800ms` / `2秒`。
做完的回执见 `sub/leg`。

## `pub/face` —— 表情
**投** hook　**取** 屏幕

```python
# 待机（微笑）
'idle'

# 聆听（眼睛下移 O 嘴）
'listen'

# 思考（眼球上瞟）
'think'

# 说话（嘴部开合动画，持续到下一条指令）
'speak'

# 开心（咧嘴）
'happy'

# 睡觉（闭眼 zzz）
'sleep'

# idle 的别名
'neutral'
```

都是 UTF-8 文本，大小写不敏感，可带旧前缀 `[SCR]:`。

## `sub/brain`、`sub/mouth`、`sub/face`、`pub/brain`、`pub/mouth`
载荷格式未定义。
