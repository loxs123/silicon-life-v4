"""
EQ12 主循环框架

设计要点：
  * __init__ 只做"搭建"：建队列 / 建 worker / 建 mqtt client
    —— 不连网、不起线程，因此可以脱离真实 broker 单独测试。
  * start()  启动全部业务 worker 和每主题发送线程（仍不连 broker，测试时可注入假 client）。
  * run()    连接 broker 并阻塞运行网络循环；Ctrl+C 或从其它线程调 stop() 后干净退出。
             config.USE_MQTT = False 时不连 broker，只跑进程内 worker（调飞书/桌面用）。
  * stop()   幂等收尾：向 pub/*、sub/* 前缀队列投 _STOP 哨兵、断开 broker、join 线程。

线程模型：所有长生命周期线程（业务 worker + 每 pub 主题一个专职发送线程）
都在 start() 一次性创建并登记进 self._threads，统一由 stop() 收尾。
"""
import queue
import threading
import time

import paho.mqtt.client as mqtt

from .config import (BROKER, PORT, PUB_TOPICS, QUEUE_ASR, QUEUE_DELAY_PUB,
                     QUEUE_DELAY_SUB, QUEUE_DESKTOP_PUB, QUEUE_DESKTOP_SUB,
                     QUEUE_FEISHU_PUB, QUEUE_FEISHU_SUB, QUEUE_TTS,
                     SUB_TOPICS, USE_MQTT)
from .workers import (EarWorker, BrainWorker, SpeakWorker, FeishuWorker,
                      DesktopWorker, DelayWorker)

_STOP = object()   # 停机哨兵：stop() 投进 pub/*、sub/* 队列，消费者 get() 到即退出


class MainLoop:
    def __init__(self, broker: str = BROKER, port: int = PORT, client=None):
        self.broker = broker
        self.port = port
        self.sub_topics = SUB_TOPICS
        self.pub_topics = PUB_TOPICS

        # 每个主题一个队列：sub/* 承载入站消息（由业务 worker 消费），
        # pub/* 承载出站消息（由专职发送线程消费并发布到 broker）。
        self.queues: dict[str, queue.Queue] = {
            t['name']: queue.Queue()
            for t in SUB_TOPICS + PUB_TOPICS
        }
        # 内部流水线队列：不直接对应 MQTT 主题（如 ASR 文本 -> TTS 语音）
        self.queues[QUEUE_ASR] = queue.Queue()
        self.queues[QUEUE_TTS] = queue.Queue()
        # 飞书网关内部队列（收发消息，进程内直连飞书 OpenAPI，不经 MQTT）。
        # 名称带 '_' 前缀：纯内部队列，不被当作 MQTT 主题，也不会被
        # stop() 哨兵（只看 'pub/'、'sub/' 前缀）或专职发送线程接管。
        self.queues[QUEUE_FEISHU_SUB] = queue.Queue()   # 收：收到消息入队
        self.queues[QUEUE_FEISHU_PUB] = queue.Queue()   # 发：出站消息队列
        # 桌面操作内部队列（同一 Windows 会话里模拟键鼠/滚轮/截屏，不经 MQTT）
        self.queues[QUEUE_DESKTOP_SUB] = queue.Queue()  # 出：截图+完成回执入队
        self.queues[QUEUE_DESKTOP_PUB] = queue.Queue()  # 入：电脑控制指令
        # 延迟消息内部队列（到点把"你之前让我做的事"推回大脑，不经 MQTT）
        self.queues[QUEUE_DELAY_PUB] = queue.Queue()    # 入：{'text': …, 'in': 秒}
        self.queues[QUEUE_DELAY_SUB] = queue.Queue()    # 出：到点的那条消息 {'text': …}

        self.qos = {t['name']: t['qos'] for t in SUB_TOPICS + PUB_TOPICS}

        # ---- worker 登记：新器官在这里加一行，start() 即统一启动 ----
        # 流水线：ear(ASR) → asr 队列 → brain(LLM) → tts 队列 → speak(TTS) → pub/speak
        ear = EarWorker(self.queues, stop_token=_STOP)
        brain = BrainWorker(self.queues)
        speak = SpeakWorker(self.queues, stop_token=_STOP)
        feishu = FeishuWorker(self.queues, stop_token=_STOP)
        desktop = DesktopWorker(self.queues, stop_token=_STOP)
        delay = DelayWorker(self.queues)      # 不吃哨兵：daemon 线程随进程退出
        self._worker_runs = [ear.run, brain.run, speak.run,
                             feishu.run, desktop.run, delay.run]

        self._threads: list[threading.Thread] = []
        self._running = False

        # mqtt client 只创建、绑回调，不连接（连接放到 run()）
        self.client = client or mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
        self.client.on_connect = self.on_connect
        self.client.on_disconnect = self.on_disconnect
        self.client.on_message = self.on_message

    # ------------------------------------------------------------- 生命周期
    def start(self):
        """启动全部业务 worker 与每主题发送线程（幂等，不连接 broker）。"""
        if self._running:
            return
        self._running = True
        self._threads = []
        for run in self._worker_runs:
            self._spawn(run)
        self._start_publishers()

    def run(self):
        """连接 broker 并阻塞运行网络循环；Ctrl+C 或其它线程调 stop() 后干净退出。"""
        self.start()
        try:
            if not USE_MQTT:
                print("[MainLoop] config.USE_MQTT = False：不连 broker，"
                      "只跑飞书 / 桌面这些进程内 worker")
                while True:               # 主线程挂着等 Ctrl+C
                    time.sleep(0.5)
            try:
                self.client.connect(self.broker, self.port, keepalive=60)
            except OSError as e:
                print(f"[MainLoop] 无法连接 broker {self.broker}:{self.port}: {e}")
                return
            self.client.loop_forever()
        except KeyboardInterrupt:
            print("[MainLoop] 收到 Ctrl+C，正在退出…")
        finally:
            self.stop()

    def stop(self):
        """优雅停机（幂等，可从任意线程调用）：投哨兵 + 断开 broker + join。

        只给 pub/* 与 sub/* 前缀的队列投 _STOP：这两类队列各自有固定消费者
        （pub/* -> 专职发送线程，sub/* -> 器官 worker），拿到哨兵即退出；
        asr/tts 等内部流水线队列不投，避免哨兵被下游 worker 当成业务数据。
        """
        if not self._running:
            return
        self._running = False

        for name, q in self.queues.items():
            if name.startswith('pub/') or name.startswith('sub/'):
                q.put(_STOP)

        # 断开 broker：让 run() 里的 loop_forever() 返回
        try:
            self.client.disconnect()
        except (ValueError, OSError, RuntimeError):
            pass  # 本来就没连上 / 已断开

        # 等待各线程退出（超时兜底；daemon 线程在进程退出时也会被结束）
        for th in self._threads:
            th.join(timeout=2)

    def _spawn(self, fn, *args) -> threading.Thread:
        th = threading.Thread(target=fn, args=args,
                              name=f"eq12-{fn.__name__}", daemon=True)
        th.start()
        self._threads.append(th)
        return th

    # ------------------------------------------------------------- mqtt 回调
    def on_connect(self, client, userdata, flags, reason_code, properties=None) -> None:
        if reason_code.is_failure:
            print(f"[MainLoop] 连接被拒绝: {reason_code}")
            return
        print(f"[MainLoop] 已连接 {self.broker}:{self.port}，"
              f"订阅 {len(self.sub_topics)} 个主题")
        for t in self.sub_topics:
            client.subscribe(t['name'], qos=t['qos'])

    def on_disconnect(self, client, userdata, disconnect_flags, reason_code,
                      properties=None):
        # 意外断线后 paho 会自动重连，on_connect 会再次触发并重订阅；
        # 主动 disconnect()（stop 流程）也会走到这里。可在此做告警/记录。
        print(f"[MainLoop] 与 broker 断开: {reason_code}")

    def on_message(self, client, userdata, msg):
        # 回调里只做"入队"，立刻返回：paho 网络循环线程永不碰业务逻辑
        self.queues[msg.topic].put(msg)

    # ------------------------------------------------------------- 发送线程
    def _start_publishers(self):
        for t in self.pub_topics:
            self._spawn(self._publish_worker, t['name'], self.queues[t['name']])

    def _publish_worker(self, q_name, q):
        """专职发送线程：q.get() 阻塞等消息，来一条发一条；收到 _STOP 哨兵则退出。"""
        while True:
            data = q.get()               # 阻塞等待，不空转、不 sleep
            if data is _STOP:
                break
            try:
                self.client.publish(q_name, data,
                                    qos=self.qos[q_name]).wait_for_publish(timeout=5)
            except (ValueError, RuntimeError, OSError) as e:
                print(f"[{q_name}] 发送失败: {e}")
            # 断线恢复后继续跑，循环不因此死掉


if __name__ == '__main__':
    MainLoop().run()
