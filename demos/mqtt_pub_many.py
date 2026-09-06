"""MQTT 并发处理消息的最小 demo —— 批量发布端

快速连续发布 N 条消息（每条模拟需要 2 秒处理），用于观察订阅端 worker 的并发效果。

用法：
    python mqtt_pub_many.py            # 发布 5 条
    python mqtt_pub_many.py 10         # 发布 10 条
"""
import sys
import time

import paho.mqtt.client as mqtt

BROKER = "127.0.0.1"
PORT = 1883
TOPIC = "demo/work"
N = int(sys.argv[1]) if len(sys.argv) > 1 else 5   # 要发的消息条数
SECONDS = 2.0                                       # 每条消息模拟的处理秒数


def main() -> None:
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
    client.connect(BROKER, PORT)
    client.loop_start()

    t_pub = time.time()
    for i in range(1, N + 1):
        payload = f"job-{i}:{SECONDS}"
        info = client.publish(TOPIC, payload, qos=1)
        info.wait_for_publish(timeout=5)
        print(f"[pub] #{i} {payload!r}", flush=True)
    print(f"[pub] 共 {N} 条已发出（耗时 {time.time() - t_pub:.2f}s）")

    client.loop_stop()
    client.disconnect()


if __name__ == "__main__":
    main()
