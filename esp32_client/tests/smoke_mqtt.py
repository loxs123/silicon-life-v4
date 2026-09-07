"""AsyncMQTT 引擎的 PC 端冒烟测试（不依赖 MicroPython / broker）。

跑法（在 esp32_client/ 目录下）：
    python tests/smoke_mqtt.py

用一个本地 asyncio 假 broker 验证：
  1. CONNECT 握手 + CONNACK 解析
  2. SUBSCRIBE 发出（每主题一包）
  3. 下行 QoS0 PUBLISH → on_message 触发
  4. 下行 QoS1 PUBLISH → 自动回 PUBACK
  5. 上行 publish() 被 broker 正确收到（帧长度/主题/载荷一致）
  6. broker 掐断连接 → 引擎自动重连并重新订阅
"""
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.mqtt import AsyncMQTT, MQTTError, _encode_str, _encode_varint  # noqa: E402


# ---------------------------------------------------------------- 假 broker
class FakeBroker:
    def __init__(self):
        self.connects = 0          # 收到 CONNECT 次数
        self.subscribes = 0        # 收到 SUBSCRIBE 包次数
        self.pub_acks = []         # 收到的 PUBACK pid
        self.rx_pub = []           # 收到的上行 (topic, payload)
        self.conn_writers = []     # 活动连接，测试可掐断

    def stats(self):
        return dict(connects=self.connects, subscribes=self.subscribes,
                    pub_acks=self.pub_acks, rx_pub=list(self.rx_pub))

    async def handler(self, reader, writer):
        self.conn_writers.append(writer)
        self.connects += 1
        try:
            while True:
                b0 = (await reader.readexactly(1))[0]
                rem = await self._read_varint(reader)
                body = await reader.readexactly(rem) if rem else b''
                kind = b0 >> 4
                if kind == 1:                      # CONNECT → CONNACK
                    writer.write(b'\x20\x02\x00\x00')
                    await writer.drain()
                elif kind == 8:                    # SUBSCRIBE → SUBACK
                    self.subscribes += 1
                    pid = body[:2]
                    writer.write(b'\x90\x03' + pid + b'\x00')
                    await writer.drain()
                elif kind == 3:                    # PUBLISH（上行）
                    qos = (b0 >> 1) & 0x03
                    tlen = int.from_bytes(body[:2], 'big')
                    topic = body[2:2 + tlen].decode('utf-8')
                    off = 2 + tlen
                    if qos == 1:
                        off += 2
                    self.rx_pub.append((topic, bytes(body[off:])))
                elif kind == 4:                    # PUBACK
                    self.pub_acks.append(body)
                elif kind == 12:                   # PINGREQ → PINGRESP
                    writer.write(b'\xd0\x00')
                    await writer.drain()
        except (asyncio.IncompleteReadError, ConnectionError):
            pass
        finally:
            writer.close()

    @staticmethod
    async def _read_varint(reader):
        value = 0
        mult = 1
        for _ in range(4):
            b = (await reader.readexactly(1))[0]
            value += (b & 0x7F) * mult
            if not (b & 0x80):
                return value
            mult *= 128
        raise MQTTError('bad varint')


async def wait_until(pred, timeout=5.0, what='condition'):
    deadline = asyncio.get_event_loop().time() + timeout
    while not pred():
        if asyncio.get_event_loop().time() > deadline:
            raise AssertionError(f'timeout waiting: {what}')
        await asyncio.sleep(0.02)


async def main():
    broker = FakeBroker()
    server = await asyncio.start_server(broker.handler, '127.0.0.1', 0)
    port = server.sockets[0].getsockname()[1]

    got = []                       # 客户端收到的下行 (topic, payload)
    c = AsyncMQTT('smoke-test', '127.0.0.1', port,
                  keepalive=1, reconnect_delay=0.2)
    c.subscribe('pub/speak', qos=0)
    c.subscribe('pub/ear', qos=0)
    c.on_message = lambda t, p: got.append((t, p))

    task = asyncio.create_task(c.run())
    try:
        await wait_until(lambda: broker.connects >= 1, what='CONNECT')
        await wait_until(lambda: broker.subscribes >= 2, what='SUBSCRIBE x2')
        assert c.connected, 'client 未进入 connected'

        # ---- 3) 下行 QoS0 PUBLISH ----
        def inbound_pub(topic, payload, qos0_header=0x30):
            body = _encode_str(topic) + payload
            return bytes([qos0_header]) + _encode_varint(len(body)) + body

        # 4) 下行 QoS1 PUBLISH（回 PUBACK 防失步；固定头 QoS1=0x32）
        q1_topic, q1_payload, q1_pid = 'pub/ear', b'start', b'\x00\x07'
        q1_body = _encode_str(q1_topic) + q1_pid + q1_payload

        async def feed():
            w = broker.conn_writers[-1]
            w.write(inbound_pub('pub/speak', b'hello-tts-12345'))
            w.write(bytes([0x32]) + _encode_varint(len(q1_body)) + q1_body)
            await w.drain()

        await feed()
        await wait_until(lambda: len(got) >= 2, what='收到 2 条下行')
        assert ('pub/speak', b'hello-tts-12345') in got, f'got={got}'
        assert ('pub/ear', b'start') in got, f'got={got}'
        await wait_until(lambda: len(broker.pub_acks) == 1, what='PUBACK')
        assert broker.pub_acks == [q1_pid], broker.pub_acks

        # ---- 5) 上行 publish ----
        await c.publish('sub/ear', b'\x00\x01\x02mic-audio')
        await wait_until(lambda: len(broker.rx_pub) == 1, what='broker 收到上行')
        assert broker.rx_pub[0] == ('sub/ear', b'\x00\x01\x02mic-audio'), broker.rx_pub

        # ---- 6) 掐断连接 → 自动重连 + 重订阅 ----
        conns_before = broker.connects
        broker.conn_writers[-1].close()
        await wait_until(lambda: not c.connected, what='客户端感知断开')
        await wait_until(lambda: broker.connects > conns_before
                         and broker.subscribes >= 4
                         and c.connected,
                         timeout=5, what='重连+重订阅')
        print('reconnect ok, subscribes =', broker.subscribes)

        print('SMOKE PASS:', broker.stats())
    finally:
        task.cancel()
        try:
            await task
        except (asyncio.CancelledError, Exception):
            pass
        server.close()
        await server.wait_closed()


if __name__ == '__main__':
    asyncio.run(main())
