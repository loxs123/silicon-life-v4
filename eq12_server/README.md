# eq12_server

EQ12「硅基生命」的服务端框架 —— 基于 **MQTT 总线 + 每主题队列 + 器官 worker** 的消息中枢。

把机器人身体的各个"器官"（brain / eye / ear / mouth / head / leg / face）看作挂在本地
MQTT broker 上的节点：本服务订阅各器官发来的数据（`sub/*` 入站），加工后把结果或指令
发回去（`pub/*` 出站）。框架负责线程模型、收发、优雅停机；每个器官的业务逻辑收敛在
一个独立的 worker 类里。

> 配套的 MQTT / 线程 / 队列原型实验在 [`../demos`](../demos)，本仓库是把这些实验
> 收敛成可复用框架的成品版。

---

## 1. 架构

### 1.1 主题约定

| 前缀 | 方向 | 含义 |
|---|---|---|
| `sub/xxx` | **入站**：服务器订阅，器官发布 | 器官 → 服务器（如 `sub/ear` 里是原始音频） |
| `pub/xxx` | **出站**：服务器发布，器官订阅 | 服务器 → 器官（如给耳朵的采集指令） |
| `asr`、`tts` | 服务器内部 | 内部流水线队列，不直接对应 MQTT 主题 |

主题与 QoS 统一在 `src/config.py` 管理。

### 1.2 内部数据流

```
MQTT broker (127.0.0.1:1883)
      ▲                            │
      │ 发布 pub/*（器官订阅）      │ 器官发布 sub/*（本服务订阅）
      │                            ▼
┌────────────────────────  MainLoop  ────────────────────────┐
│                                                            │
│  on_message：只把 msg 丢进 queues[msg.topic]，立刻返回      │
│     → paho 网络循环线程永不碰业务，不会阻塞心跳/收发         │
│                                                            │
│  queues（dict[str, queue.Queue]，每个主题一个队列）          │
│    sub/*  入站队列   ←── 器官 worker 消费（如 EarWorker）   │
│    pub/*  出站队列   ←── 专职发送线程消费并 publish          │
│    asr/tts 内部流水线（占位）                               │
│                                                            │
│  线程模型：所有线程在 start() 一次性创建并登记，stop() 统一收尾│
└────────────────────────────────────────────────────────────┘
```

**发送端**：每个 `pub/*` 主题有且只有一个专职发送线程，阻塞在 `q.get()` 上，
来一条发一条（`wait_for_publish` 等待确认，单队列串行保证顺序）；断线/失败只打印
不退出，恢复后继续跑。

**接收端**：业务 worker（如 `EarWorker`）阻塞在对应 `sub/*` 队列上，取到消息做
ASR 等加工，结果写入目标器官的出站队列（如 `pub/brain`），由发送线程发布。

---

## 2. 快速开始

依赖：Python ≥ 3.10、`paho-mqtt`、本机已运行 Mosquitto（默认 `127.0.0.1:1883`）。

```bash
pip install -r ../requirements.txt    # 或按需单装: pip install paho-mqtt dashscope lark-oapi pyautogui

# 终端 1：启动 broker（以 Windows 为例）
mosquitto -v

# 终端 2：启动服务
python run.py          # 或 python -m src.main_loop

# Ctrl+C 干净退出：断开 broker → 线程收尾（哨兵）→ join
```

> 飞书凭据（FEISHU_APP_ID / FEISHU_APP_SECRET）与 DashScope Key 一起放在
> 仓库根的 `set_dashscope_env.cmd`（该文件已被 gitignore，勿提交）。
> `pyautogui`（含截屏所需的 Pillow）是 DesktopWorker 运行桌面键鼠/截屏用的，
> 不需要桌面操作时可去掉。

## 3. 代码结构

```
eq12_server/
├── run.py                  # 入口：MainLoop().run()
└── src/
    ├── config.py           # broker 地址 + SUB_TOPICS / PUB_TOPICS（name + qos）
    ├── main_loop.py        # 框架主体：队列、线程、生命周期、mqtt 回调、_STOP 哨兵
    └── workers/
        ├── __init__.py     # worker 统一导出
        ├── ear_worker.py   # 示例器官 worker（ASR 尚未实现，TODO）
        ├── brain_worker.py # 大脑：asr 文本 → 流式 LLM → tts
        ├── speak_worker.py # 嘴：tts 文本 → 流式 TTS → pub/speak
        ├── feishu_worker.py# 飞书网关：长连接收发文字/图片（见 §6.1）
        ├── desktop_worker.py# 桌面操作：键鼠/滚轮/截屏（见 §6.2）
        └── delay_worker.py # 延迟消息：到点把"你之前让我做的事"推回大脑（见 §6.3）
```

---

## 4. 生命周期

```
MainLoop()
   └─ __init__：只搭结构（队列/worker/mqtt client + 回调）   ← 不连网、不起线程
        │
        ▼
      start()   启动全部 worker + 每 pub 主题一个发送线程    ← 仍不连 broker
        │
        ▼
      run()     连接 broker → loop_forever() 阻塞运行        ← Ctrl+C / stop() 后退出
        │
        ▼
      stop()    向 pub/*、sub/* 前缀队列投 _STOP 哨兵
                → 断开 broker → join 各线程（超时兜底）
```

- **`__init__` 不做网络操作**：因此可以脱离真实 broker 单独测试（见 §7）。
- **`stop()` 幂等**，可从任意线程调用；`run()` 的 `finally` 里兜底执行。
- **停机协议**：`_STOP = object()` 哨兵由 `stop()` 只投给 **`pub/`、`sub/` 前缀**
  的队列（这两类队列各有固定消费者，拿到哨兵即退出）；`asr`/`tts` 等内部队列不投，
  避免哨兵被下游 worker 当成业务数据。消费者用 `if item is _STOP: break`（worker 通过
  构造参数 `stop_token` 注入，避免 main_loop ↔ workers 循环导入）。
- **断线重连**：paho 自动重连，`on_connect` 重新订阅全部 `sub/*`；
  `on_disconnect` 留作告警/记录钩子。

---

## 5. 新增一个器官 worker

以「眼睛」为例，四步：

1. **`src/config.py`**：在 `SUB_TOPICS` / `PUB_TOPICS` 各加 `{'name': 'sub/eye', 'qos': 0}` 等条目。
2. **新建 `src/workers/eye_worker.py`**：

   ```python
   from queue import Queue

   class EyeWorker:
       def __init__(self, queues: dict[str, Queue], stop_token=None):
           self.queues = queues
           self.stop_token = stop_token

       def run(self):
           while True:
               frame = self.queues['sub/eye'].get()
               if self.stop_token is not None and frame is self.stop_token:
                   break
               # TODO: 视觉处理
               # text = self.detect(frame)
               # self.queues['pub/brain'].put(text)
   ```

3. **`src/workers/__init__.py`** 导出新 worker。
4. **`src/main_loop.py` 的 `__init__` 登记**：

   ```python
   ear = EarWorker(self.queues, stop_token=_STOP)
   eye = EyeWorker(self.queues, stop_token=_STOP)
   self._worker_runs = [ear.run, eye.run]
   ```

框架主体（队列、线程、收发、停机）无需再动。

---

## 6. 进程内工具 worker（FeishuWorker 飞书 / DesktopWorker 桌面 / DelayWorker 延迟消息）

飞书和桌面操作都是 eq12_server **进程内直连外部世界**的口，不经过 MQTT
（MQTT 只服务 ESP32 器官）。它们各自用两条**内部队列**（在 `src/main_loop.py`
里与 asr/tts 同级创建，名称带 `_` 前缀表示纯内部队列：不是 MQTT 主题，
`stop()` 的 pub/*、sub/* 哨兵与专职发送线程都不会碰它们）：

### 6.1 飞书网关（FeishuWorker）

飞书是「远程聊天口」：用户在飞书里给机器人发消息，机器人回复（文字/图片）。
`FeishuWorker` 用官方 `lark-oapi` SDK 直连飞书 OpenAPI（WebSocket 长连接收
事件、HTTPS 发消息）：

| 队列 | 方向 | 内容 |
|---|---|---|
| `_sub/feishu` | **收**：长连接收到用户消息 → 打包 dict 入队 | 下游（大脑/桥接）从这里消费 |
| `_pub/feishu` | **发**：大脑/上游把出口消息放进此队列 → 本 worker 消费并调用飞书 API 发出 | 发文字 / 发图 |

载荷协议（决策统一在 brain）：

```python
# _sub/feishu 里的 dict（收到用户消息）
{'feishu': True, 'text': '你好', 'message_id': 'om_...',
 'chat_id': 'oc_...', 'sender': 'ou_...'}
{'feishu': True, 'type': 'image', 'image_key': 'img_v2_...',
 'message_id': 'om_...', 'chat_id': 'oc_...', 'sender': 'ou_...'}

# 往 _pub/feishu 放这些，即触发发送（两种都是 dict）
{'text': '你好'}                               # 发一条文字
{'img': '<base64 JPEG>'}                       # 发一张图（如 <cam> 拍照结果）
#   chat_id 通常不用传 → 自动回到「消息来的那个会话」；
#   只有要发给别的会话时才显式指定
```

目标会话的解析顺序：载荷的 `chat_id` → 最近一次收到消息的会话
→ `config.FEISHU_DEFAULT_CHAT_ID`（重启后还没人说话时的兜底）。

两种载荷都走 `im.v1.message.create`（**主动发新消息**，不引用任何历史消息），
所以不需要 `message_id`。

- **依赖/凭据**：`pip install lark-oapi`；`FEISHU_APP_ID` / `FEISHU_APP_SECRET`
  放在仓库根 `set_dashscope_env.cmd`（已被 gitignore）。lark-oapi 未安装或凭据
  缺失时该 worker 只打印提示即退出，不影响其余链路。
- **当前边界**：收到消息只入队 + 打日志，**决策尚未接线** —— BrainWorker 还只
  消费内部 `asr` 队列（语音链路），还没消费 `_sub/feishu`、也没往 `_pub/feishu`
  写回复；本步只搭好"飞书口"。收到图片也只记录 image_key，视觉识别/按 key
  下载留待以后。
- **生命周期**：两条内部队列不吃 `_STOP` 哨兵，长连接线程与主循环是 daemon，
  随进程退出（与消费 asr/tts 的 worker 一致）；`FeishuWorker.close()` 幂等、
  随时可调，用于主动停长连接。

### 6.2 桌面操作（DesktopWorker）

EQ12「硅基生命」跑在桌面 Windows 主机上，这台电脑就是它可以操控的"工具"。
`DesktopWorker` 用 `pyautogui`（+ Pillow 截屏）在同一会话模拟键鼠，让上游
（brain）能"看屏幕 → 想 → 操作"：

| 队列 | 方向 | 内容 |
|---|---|---|
| `_sub/desktop` | **出**：本 worker 放结果入队（截图 + 指令完成回执） | 下游（视觉理解/大脑）从这里消费 |
| `_pub/desktop` | **入**：上游把控制指令放进此队列 → 本 worker 消费并执行 | 键鼠 / 滚轮 / 截屏 / 剪切板 |

`_pub/desktop` 指令格式：

```python
{"type": "keyboard", "value": "A",  "time": 3}    # 同时按下 value 全部键并保持 time 秒
                                                  #   "AZ" = A+Z 同按；"CTRLALTDELETE" = Ctrl+Alt+Delete
                                                  #   ⚠️ 按键名按【最长匹配】切分：LEFT/F10 等不会被拆成字母
{"type": "mouse",   "direction": "UP|DOWN|LEFT|RIGHT", "value": 12}   # 鼠标相对移动 value 像素
{"type": "scroll",  "direction": "UP|DOWN", "value": 12}              # 滚轮滚动 value 格
{"type": "screenshot"}                              # 截一张全屏 JPEG → 放进 _sub/desktop（按需截，仿 pub/eye b'photo'）
{"type": "clipboard", "value": "要写进剪切板的文字"}   # 写剪切板（空串=清空）；配合 keyboard 的 CTRLV 即可粘贴
```

`_sub/desktop` 截图载荷（字段对齐 esp32 的 `sub/eye` 照片 JSON，仅多 `fmt`）：

```python
{'type': 'screen', 'time': <unix秒>, 'size': <JPEG字节数>,
 'width': W, 'height': H, 'fmt': 'jpeg', 'data': '<base64 JPEG>'}
```

`_sub/desktop` 完成回执（与截图同队列、按序；每条指令**真执行成功**后追加一条，
说明刚完成的是哪条指令）：

```python
{'type': 'done', 'time': <unix秒>, 'command': <原始指令 dict>}
# keyboard 已按完抬起 / mouse 已移动 / scroll 已滚 /
# screenshot 已把截图入队（紧随其后的 {'type':'screen'} 即结果）/ clipboard 已写入剪切板。
# 指令无效（缺参/方向错/无按键）或执行抛异常时只打日志、不回执。
```

- **依赖**：`pip install pyautogui`（Windows 下截屏自动依赖 Pillow）。
  未安装时该 worker 打印提示即退出，不影响其余链路。
- **安全**：执行的是 OS 级键鼠指令，等同真人操作电脑——只消费 `_pub/desktop`
  里明确下发的指令，不做自主判断。worker 会关掉 pyautogui 的 FailSafe
  （默认鼠标到屏幕四角抛异常，机器人需要能点角上的关闭按钮/开始菜单）。
- **当前边界**：brain 尚未接线（读 `_sub/desktop` 截图与完成回执、往 `_pub/desktop`
  发指令）；按键串大小写靠显式 `SHIFT` 组合（如 `"SHIFTA"` 出大写 A）。

### 6.3 延迟消息（DelayWorker）

「15 分钟之后提醒我喝水」这类需求**不能靠 hook 里 `sleep`**（一睡就把 brain 主循环
拖死），交给 `DelayWorker` 记着，到点推一条消息出来。**它只碰这两条队列，不关联
任何别的链路**（不碰 asr / tts / 飞书 / 桌面 / MQTT）。

```python
# 入：_pub/delay —— 只有这一种格式
{'text': '提醒我喝水', 'in': 900}      # 900 秒后到点（"15 分钟" = 900，自己乘好）

# 出：_sub/delay —— 到点推这一条
{'text': '15 分钟之前你让我提醒我喝水，现在到点了，你来接着办。',
 'in': 900, 'due_at': <unix>, 'fired_at': <unix>}
```

- **出队列的 `text` 就是那句话**（`config.DELAY_ECHO_TEMPLATE` 套 `{ago}` + `{text}`，
  「15 分钟之前 / 刚刚」由 `format_ago` 生成）；谁消费 `_sub/delay` 谁决定下一步怎么做。
- **轮询式主循环**：每轮 `sleep DELAY_POLL_S`（默认 1 秒）→ 非阻塞取空 `_pub/delay` →
  把到点的推进 `_sub/delay`，所以到点精度是 **±DELAY_POLL_S**（提醒场景够用，也不需要
  `get(timeout=)`）。
- **格式固定，不做校验**：缺键/类型不对就在 worker 线程里直接抛异常（`KeyError` 之类），
  不兜底、不静默吞掉。
- **停机**：本 worker 不吃哨兵（`_pub/delay` 没有别的消费者，也不用停它），线程是
  daemon，随进程一起结束。
- **依赖**：纯标准库；冒烟测试 `python tests/test_delay_worker.py`（免依赖、不联网）。
- **当前边界**：待办只在内存里，**进程重启就没了**；没有取消 / 查询接口。

---

## 7. 不连 broker 的测试

`start()` 不连接网络，`MainLoop(broker=..., client=...)` 可注入假 client：

```python
import time
from src.main_loop import MainLoop

class FakeClient:                      # 只记录，不联网
    def __init__(self):
        self.sent, self.connected = [], False
    def connect(self, *a, **k):        self.connected = True
    def loop_forever(self):            time.sleep(0.2)
    def disconnect(self):              self.connected = False
    def publish(self, topic, payload, qos=0):
        self.sent.append((topic, payload))
        class Info:
            def wait_for_publish(self, **k): return True
        return Info()

loop = MainLoop(client=FakeClient())
loop.start()
loop.queues['pub/ear'].put(b'hello')   # 出站 → 发送线程"发布"
time.sleep(0.1)
assert loop.client.sent[0] == ('pub/ear', b'hello')

class Msg:                             # 手动模拟入站
    topic = 'sub/ear'
loop.on_message(None, None, Msg())
assert loop.queues['sub/ear'].qsize() == 1

loop.stop()                            # 哨兵 + 断开 + 线程退出
assert not any(t.is_alive() for t in loop._threads)
```

---

## 8. 当前状态与已知边界

- [x] 框架主体：队列路由、专职发送线程、生命周期、优雅停机
- [x] FeishuWorker 飞书网关：长连接收发文字/图片，`_sub/feishu` 入队 /
      `_pub/feishu` 出队（brain 接线待做，见 §6.1）
- [x] DesktopWorker 桌面操作：`_pub/desktop` 键鼠/滚轮/截屏指令执行，
      `_sub/desktop` 出 JPEG 截图 + 指令完成回执 `{'type':'done',...}`
      （brain 接线待做，见 §6.2）
- [x] DelayWorker 延迟消息：`_pub/delay` 投 `{'text':…, 'in': 秒}` → 到点把
      「15 分钟之前你让我…」推进 `_sub/delay`（只碰这两条队列；下游接线待做，
      待办只在内存里，见 §6.3）
- [ ] `EarWorker` 的 ASR 尚未实现（TODO）
- [ ] `esp32_client` 器官端已实现 ear/speak/eye/leg/face（见其 README）；本端
      `sub/eye`（照片）、`pub/eye`/`pub/leg`/`pub/face`（触发看/动/表情）的消费与触发 worker 待接
- [ ] 消息载荷目前是**裸 bytes**；器官多了以后建议引入 JSON 信封
      （`{from, to, seq, ts, type, payload}`）以便按内容路由
- [ ] worker 循环内异常会使该线程静默退出，尚无日志/自动重启
- [ ] 每队列目前一个消费者；若将来多 worker 共消费同一 sub 队列，
      `stop()` 每队列只投一个哨兵会漏停（需按消费者数投放）
- [ ] 无消费者的 sub 队列在每次 `stop()` 后会残留一个 `_STOP` 哨兵；
      若之后热重启并给该队列新加 worker，注意先清掉旧哨兵
- [ ] DelayWorker 只支持一次性延迟（无"每 N 分钟重复"），待办只在内存里、进程重启即丢；
      它不吃哨兵（线程 daemon，随进程退出）
