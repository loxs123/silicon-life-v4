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
pip install paho-mqtt

# 终端 1：启动 broker（以 Windows 为例）
mosquitto -v

# 终端 2：启动服务
python run.py          # 或 python -m src.main_loop

# Ctrl+C 干净退出：断开 broker → 线程收尾（哨兵）→ join
```

## 3. 代码结构

```
eq12_server/
├── run.py                  # 入口：MainLoop().run()
└── src/
    ├── config.py           # broker 地址 + SUB_TOPICS / PUB_TOPICS（name + qos）
    ├── main_loop.py        # 框架主体：队列、线程、生命周期、mqtt 回调、_STOP 哨兵
    └── workers/
        ├── __init__.py     # worker 统一导出
        └── ear_worker.py   # 示例器官 worker（ASR 尚未实现，TODO）
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

- **`__init__` 不做网络操作**：因此可以脱离真实 broker 单独测试（见 §6）。
- **`stop()` 幂等**，可从任意线程调用；`run()` 的 `finally` 里兜底执行。
- **停机协议**：`_STOP = object()` 哨兵由 `stop()` 只投给 **`pub/`、`sub/` 前缀**
  的队列（这两类队列各有固定消费者，拿到哨兵即退出）；`asr`/`tts` 内部队列不投，
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

## 6. 不连 broker 的测试

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

## 7. 当前状态与已知边界

- [x] 框架主体：队列路由、专职发送线程、生命周期、优雅停机
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
