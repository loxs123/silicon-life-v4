"""Minimal MQTT subscriber demo (paho-mqtt).

Usage:
    python mqtt_sub.py

Listen for messages forever on topic 'demo/test' (Ctrl+C to stop).
"""
import paho.mqtt.client as mqtt

BROKER = "127.0.0.1"   # local Mosquitto broker
PORT = 1883            # default MQTT port
TOPIC = "demo/test"    # topic to subscribe to


def on_connect(client, userdata, flags, reason_code, properties=None):
    print(f"[sub] connected to {BROKER}:{PORT}, reason_code={reason_code}")
    client.subscribe(TOPIC, qos=1)


def on_message(client, userdata, msg):
    print(f"[sub] received on '{msg.topic}' (qos={msg.qos}): {msg.payload.decode()}")


def main() -> None:
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
    client.on_connect = on_connect
    client.on_message = on_message

    client.connect(BROKER, PORT)
    print(f"[sub] listening on {BROKER}:{PORT} topic '{TOPIC}' (Ctrl+C to stop)")
    client.loop_forever()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n[sub] stopped by user")
