"""esp32 器官端主循环 —— eq12_server/src/main_loop.py 的协程镜像。

设计要点（与 eq12_server 一一对应，只是 线程→协程、paho→AsyncMQTT）：

  eq12_server（线程 + paho）           esp32_client（asyncio + AsyncMQTT）
  ---------------------------------    ---------------------------------
  __init__ 只搭建：队列/worker/client   __init__ 只搭建（不联网、不起任务）
  start() 起 worker + 发送线程          run() 里 asyncio.create_task(...)
  run()  loop_forever() 阻塞运行        run() 阻塞等待 _stopped / 被取消
  stop() 哨兵 + disconnect + join       stop() 哨兵入队 + 超时取消任务
  on_message 只入队路由                 同名，只入队路由（同一句注释都适用）
  每 pub 主题一个专职发送线程            每 pub 主题一个发送任务（单条 TCP 连接
                                        本来就只能串行，一个任务即可）
  asr/tts 内部流水线队列（有 brain）    无 —— 大脑在 EQ12 主机上，esp32 没有
  _STOP 哨兵                            _STOP 哨兵（消费者 get() 到即退出）

esp32 端只承担两个器官：ear（麦克风上行）与 speak（下行 TTS 播放）。
"""
try:
    import asyncio
except ImportError:
    import uasyncio as asyncio

from .config import BROKER, PORT, CLIENT_ID, KEEPALIVE, QOS, Q_CAP
from .config import PUB_TOPICS, SUB_TOPICS
from .mqtt import AsyncMQTT
from .workers import EarWorker, SpeakWorker

_STOP = object()   # 停机哨兵：stop() 投进队列，消费者 get() 到即退出（同 eq12）


class _Msg:
    """入站消息：与 eq12 里 paho 的 MQTTMessage 对齐，worker 用 item.payload 取值。"""
    __slots__ = ('topic', 'payload')

    def __init__(self, topic: str, payload: bytes):
        self.topic = topic
        self.payload = payload


class _Queue:
    """有界 asyncio 队列（不依赖 micropython-lib 的 asyncio.Queue）。

    满则丢最旧：流式音频场景宁可丢老数据也不能让内存涨到 OOM。
    单消费者，Event 唤醒足够；put_nowait/get 对应 eq12 的 queue.Queue。
    """

    def __init__(self, maxsize: int = 0):
        self._maxsize = maxsize
        self._items = []
        self._evt = asyncio.Event()

    def put_nowait(self, item):
        if self._maxsize and len(self._items) >= self._maxsize:
            self._items.pop(0)          # 满：丢最旧，保新鲜
        self._items.append(item)
        self._evt.set()

    async def get(self):
        while not self._items:
            self._evt.clear()
            await self._evt.wait()
        return self._items.pop(0)


class MainLoop:
    def __init__(self, broker: str = BROKER, port: int = PORT):
        self.broker = broker
        self.port = port
        self.sub_topics = SUB_TOPICS
        self.pub_topics = PUB_TOPICS
        self.qos = QOS

        # 每个主题一个队列（同 eq12）：sub 视角=下行 pub/* 入站（worker 消费），
        # pub 视角=上行 sub/* 出站（发送任务消费并 publish 到 broker）。
        self.queues = {
            t['name']: _Queue(Q_CAP.get(t['name'], 0))
            for t in SUB_TOPICS + PUB_TOPICS
        }

        # ---- worker 登记：新器官在这里加一行，run() 即统一启动（同 eq12 注释）----
        # esp32 无大脑：ear(采麦克风上行) / speak(下行 TTS 播放)
        ear = EarWorker(self.queues, stop_token=_STOP)
        speak = SpeakWorker(self.queues, stop_token=_STOP)
        self._worker_runs = [ear.run, speak.run]

        self._tasks = []
        self._stopped = asyncio.Event()

        # mqtt client 只创建、绑回调、登记订阅，不连接（连接放到 run()，同 eq12）
        self.mqtt = AsyncMQTT(CLIENT_ID, self.broker, self.port,
                              keepalive=KEEPALIVE)
        self.mqtt.on_connect = self.on_connect
        self.mqtt.on_message = self.on_message

    # ------------------------------------------------------------- 生命周期
    async def run(self):
        """启动全部任务并阻塞运行；stop() 后干净退出（对应 eq12 的 run()）。"""
        for t in self.sub_topics:
            self.mqtt.subscribe(t['name'], qos=t['qos'])

        self._tasks = [asyncio.create_task(self.mqtt.run())]
        for t in self.pub_topics:                       # 每 pub 主题一个发送任务
            self._tasks.append(asyncio.create_task(
                self._publish_worker(t['name'], self.queues[t['name']])))
        for run in self._worker_runs:                   # 业务 worker
            self._tasks.append(asyncio.create_task(run()))
        print(f'[MainLoop] 已启动 {len(self._tasks)} 个协程任务')

        try:
            await self._stopped.wait()
        except asyncio.CancelledError:
            raise                                       # Ctrl+C：交给 finally 收尾
        finally:
            await self.stop()                           # 兜底：无论怎么退出都停干净

    async def stop(self):
        """优雅停机（幂等）：哨兵入队 → 等任务自然退出 → 超时取消（同 eq12 的 join
        语义：eq12 join(timeout=2)，这里用 2s 超时后 cancel 兜底）。"""
        if not self._tasks:
            return
        self._stopped.set()

        for q in self.queues.values():
            q.put_nowait(_STOP)         # 消费者（worker/发送任务）拿到即退出

        for _ in range(40):             # 最多等 2s（40 × 50ms）
            if all(t.done() for t in self._tasks):
                break
            await asyncio.sleep(0.05)
        for t in self._tasks:
            if not t.done():
                t.cancel()              # 兜底：mqtt 引擎这类无哨兵可收的任务
        for t in self._tasks:
            try:
                await t
            except (Exception, asyncio.CancelledError):
                pass
        self._tasks = []
        print('[MainLoop] 已停止')

    # ------------------------------------------------------------- mqtt 回调
    def on_connect(self) -> None:
        # 连接/重连后引擎已自动重订阅登记过的主题，这里只做提示（对应 eq12 的
        # on_connect 里"订阅全部 SUB_TOPICS"那一段，职责移进了引擎）
        print(f'[MainLoop] 已连接 {self.broker}:{self.port}，'
              f'订阅 {len(self.sub_topics)} 个主题')

    def on_message(self, topic: str, payload: bytes) -> None:
        # 回调里只做"入队"，立刻返回：mqtt 读循环永不碰业务（同 eq12 那一句）
        q = self.queues.get(topic)
        if q is not None:
            q.put_nowait(_Msg(topic, payload))

    # ------------------------------------------------------------- 发送任务
    async def _publish_worker(self, q_name: str, q):
        """专职发送任务：q.get() 阻塞等消息，来一条发一条；收到 _STOP 即退出
        （对应 eq12 的 _publish_worker / 每主题专职发送线程）。"""
        while True:
            data = await q.get()
            if data is _STOP:
                break
            if not self.mqtt.connected:   # 断线期丢弃音频：不堆积、保新鲜
                continue
            try:
                await self.mqtt.publish(q_name, data, qos=self.qos.get(q_name, 0))
            except (ValueError, OSError) as e:
                print(f'[{q_name}] 发送失败: {e}')
            # 重连恢复后继续跑，循环不因此死掉（同 eq12）
