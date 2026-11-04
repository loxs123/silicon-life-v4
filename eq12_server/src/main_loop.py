"""EQ12 主循环：建队列 / worker / mqtt client，start() 起线程，run() 连 broker 阻塞，stop() 收尾。"""
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

        self.queues: dict[str, queue.Queue] = {
            t['name']: queue.Queue()
            for t in SUB_TOPICS + PUB_TOPICS
        }
        self.queues[QUEUE_ASR] = queue.Queue()          # ASR 文本 -> TTS
        self.queues[QUEUE_TTS] = queue.Queue()
        self.queues[QUEUE_FEISHU_SUB] = queue.Queue()   # 飞书收
        self.queues[QUEUE_FEISHU_PUB] = queue.Queue()   # 飞书发
        self.queues[QUEUE_DESKTOP_SUB] = queue.Queue()  # 截图 + 回执
        self.queues[QUEUE_DESKTOP_PUB] = queue.Queue()  # 桌面指令
        self.queues[QUEUE_DELAY_PUB] = queue.Queue()    # {'text': …, 'in': 秒}
        self.queues[QUEUE_DELAY_SUB] = queue.Queue()    # 到点的那条消息

        self.qos = {t['name']: t['qos'] for t in SUB_TOPICS + PUB_TOPICS}

        # 新器官在这里加一行，start() 统一启动
        ear = EarWorker(self.queues, stop_token=_STOP)
        brain = BrainWorker(self.queues)
        speak = SpeakWorker(self.queues, stop_token=_STOP)
        feishu = FeishuWorker(self.queues, stop_token=_STOP)
        desktop = DesktopWorker(self.queues, stop_token=_STOP)
        delay = DelayWorker(self.queues)
        self._worker_runs = [ear.run, brain.run, speak.run,
                             feishu.run, desktop.run, delay.run]

        self._threads: list[threading.Thread] = []
        self._running = False

        self.client = client or mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
        self.client.on_connect = self.on_connect
        self.client.on_disconnect = self.on_disconnect
        self.client.on_message = self.on_message

    def start(self):
        if self._running:
            return
        self._running = True
        self._threads = []
        for run in self._worker_runs:
            self._spawn(run)
        self._start_publishers()

    def run(self):
        self.start()
        try:
            if not USE_MQTT:
                print("[MainLoop] config.USE_MQTT = False：不连 broker，"
                      "只跑飞书 / 桌面这些进程内 worker")
                while True:
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
        if not self._running:
            return
        self._running = False

        for name, q in self.queues.items():
            if name.startswith('pub/') or name.startswith('sub/'):
                q.put(_STOP)

        try:
            self.client.disconnect()
        except (ValueError, OSError, RuntimeError):
            pass

        for th in self._threads:
            th.join(timeout=2)

    def _spawn(self, fn, *args) -> threading.Thread:
        th = threading.Thread(target=fn, args=args,
                              name=f"eq12-{fn.__name__}", daemon=True)
        th.start()
        self._threads.append(th)
        return th

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
        print(f"[MainLoop] 与 broker 断开: {reason_code}")

    def on_message(self, client, userdata, msg):
        self.queues[msg.topic].put(msg)

    def _start_publishers(self):
        for t in self.pub_topics:
            self._spawn(self._publish_worker, t['name'], self.queues[t['name']])

    def _publish_worker(self, q_name, q):
        while True:
            data = q.get()
            if data is _STOP:
                break
            try:
                self.client.publish(q_name, data,
                                    qos=self.qos[q_name]).wait_for_publish(timeout=5)
            except (ValueError, RuntimeError, OSError) as e:
                print(f"[{q_name}] 发送失败: {e}")


if __name__ == '__main__':
    MainLoop().run()
