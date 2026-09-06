"""Minimal MQTT publisher demo (paho-mqtt).

Usage:
    python mqtt_pub.py                     # send a default hello message
    python mqtt_pub.py "your message"      # send a custom message
"""
import sys
import threading
import time

import paho.mqtt.client as mqtt

BROKER = "127.0.0.1"   # local Mosquitto broker
PORT = 1883            # default MQTT port
TOPIC = "demo/test"    # topic to publish on


def main() -> None:
    msg = " ".join(sys.argv[1:]) or f"hello from publisher at {time.strftime('%H:%M:%S')}"

    connected = threading.Event()

    def on_connect(client, userdata, flags, reason_code, properties=None):
        connected.set()
        print(f"[pub] connected to {BROKER}:{PORT}, reason_code={reason_code}")

    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
    client.on_connect = on_connect

    client.connect(BROKER, PORT)
    client.loop_start()

    if not connected.wait(timeout=5):
        print("[pub] ERROR: could not connect to the broker")
        sys.exit(1)

    info = client.publish(TOPIC, msg, qos=1)
    info.wait_for_publish(timeout=5)
    print(f"[pub] sent: '{msg}'  ->  topic '{TOPIC}' (mid={info.mid})")

    client.loop_stop()
    client.disconnect()


if __name__ == "__main__":
    main()
