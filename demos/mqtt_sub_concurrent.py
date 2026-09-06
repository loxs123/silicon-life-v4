"""MQTT 并发处理消息的最小 demo —— 订阅端（worker 线程池版）

设计要点：
  1. on_message 回调只做"入队"并立刻返回
     -> paho 的网络循环线程永远不会被业务阻塞（收消息/心跳都不被拖慢）
  2. N 个 worker 线程从队列取消息，"真正的处理"（这里用 sleep 模拟耗时任务）在
     worker 线程里并行执行

用法：
    python mqtt_sub_concurrent.py            # 默认 3 个 worker，配合 mqtt_pub_many.py
    python mqtt_sub_concurrent.py 5          # 指定 worker 数量

消息格式约定：payload 形如  "job-1:2"  ->  任务名 job-1，需要处理 2 秒
"""
import queue
import sys
import threading
import time

import paho.mqtt.client as mqtt

BROKER = "127.0.0.1"
PORT = 1883
TOPIC = "demo/work"

WORKERS = int(sys.argv[1]) if len(sys.argv) > 1 else 3   # 并发处理线程数

task_queue: "queue.Queue[mqtt.MQTTMessage]" = queue.Queue()
print_lock = threading.Lock()
t0 = time.monotonic()   # 所有线程共用的计时零点


def log(line: str) -> None:
    """加锁打印，避免多线程输出互相穿插。"""
    with print_lock:
        print(f"[t={time.monotonic() - t0:6.2f}] {line}", flush=True)


def on_message(client, userdata, msg) -> None:
    # 回调里绝不 sleep / 做耗时操作，只入队，立刻返回
    if msg.topic == "demo/cmd":
        
def worker(wid: int) -> None:
    while True:
        msg = task_queue.get()
        payload = msg.payload.decode()
        try:
            seconds = float(payload.rsplit(":", 1)[-1])   # "job-1:2" -> 2.0
        except ValueError:
            seconds = 1.0

        log(f"[w{wid}] 开始处理 {payload!r}（需要 {seconds}s）")
        time.sleep(seconds)          # 模拟真正的耗时业务
        log(f"[w{wid}] 完成   {payload!r}")
        task_queue.task_done()


def on_connect(client, userdata, flags, reason_code, properties=None) -> None:
    log(f"已连接 {BROKER}:{PORT} (reason_code={reason_code})，订阅 {TOPIC}")
    client.subscribe(TOPIC, qos=1)


def main() -> None:
    for i in range(1, WORKERS + 1):
        threading.Thread(target=worker, args=(i,), daemon=True).start()
    log(f"已启动 {WORKERS} 个 worker 线程，等待消息…（Ctrl+C 退出）")

    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
    client.on_connect = on_connect
    client.on_message = on_message
    client.connect(BROKER, PORT)
    client.loop_forever()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        log("订阅端退出")
