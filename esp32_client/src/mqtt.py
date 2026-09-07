"""最小 asyncio MQTT 客户端 —— eq12_server 里 paho-mqtt 的协程替代。

只依赖 asyncio + struct（MicroPython / CPython 通用，无需安装任何第三方库），
按 MQTT 3.1.1 裸协议实现 QoS0 收发；若收到意外的 QoS1 下行包也会回 PUBACK
防协议失步。

结构对照 eq12_server（线程 + paho）：
    paho.Client              -> 本文件的 AsyncMQTT
    client.loop_forever()    -> AsyncMQTT.run()（重连循环，每会话一个读循环）
    client.connect()         -> 引擎内部 _session()，连接后自动重订阅
    on_connect / on_message  -> 同名回调字段（on_connect 只做提示，无需手动
                                 subscribe——登记过的订阅在每次重连后自动恢复）

线程安全说明：协程间没有抢占，_send() 先 write（不 yield，整帧原子入缓冲）
再 drain，因此多个协程（发布任务 / 引擎 ping / SUBACK）并发写也不会出现半帧
交错。
"""
try:
    import asyncio
except ImportError:          # MicroPython < 1.23 的兼容写法
    import uasyncio as asyncio

import struct


class MQTTError(Exception):
    """连接级错误：触发 run() 里的重连。"""


def _encode_varint(value: int) -> bytes:
    """MQTT 剩余长度（variable byte integer）编码。"""
    out = bytearray()
    while True:
        b = value % 128
        value //= 128
        if value:
            b |= 0x80
        out.append(b)
        if not value:
            return bytes(out)


def _encode_str(s) -> bytes:
    """UTF-8 字符串 → 2 字节长度前缀 + 内容。"""
    if isinstance(s, str):
        s = s.encode('utf-8')
    return struct.pack('>H', len(s)) + s


class AsyncMQTT:
    def __init__(self, client_id: str, server: str, port: int = 1883,
                 keepalive: int = 60, reconnect_delay: float = 2.0):
        self.client_id = client_id
        self.server = server
        self.port = port
        self.keepalive = keepalive
        self.reconnect_delay = reconnect_delay

        self.connected = False          # 供发送方判断当前是否可发
        self.on_connect = None          # 连接建立回调（同步函数，仅提示/打日志）
        self.on_message = None          # (topic: str, payload: bytes) -> None

        self._topics = []               # 订阅清单：每次(重)连接后自动重订阅
        self._reader = None
        self._writer = None

    # ------------------------------------------------------------- 对外 API
    def subscribe(self, topic: str, qos: int = 0) -> None:
        """登记订阅（连接前调用；连接/重连后由引擎自动重订阅）。"""
        if (topic, qos) not in self._topics:
            self._topics.append((topic, qos))

    async def publish(self, topic: str, payload=b'', qos: int = 0) -> None:
        """发布一条 QoS0 消息；须在 connected 之后调用。"""
        if qos:
            raise ValueError('本最小客户端仅支持 QoS0 上行')
        body = _encode_str(topic) + bytes(payload)
        await self._send(b'\x30' + _encode_varint(len(body)) + body)

    async def run(self):
        """重连循环：每轮一个会话（连接 → 订阅 → 读消息），断开后延时重试。"""
        while True:
            try:
                await self._session()
            except asyncio.CancelledError:
                raise                     # 停机：原样上抛，不做重连
            except Exception as e:
                print(f'[mqtt] {self.server}:{self.port} 断开: {e}')
            await asyncio.sleep(self.reconnect_delay)

    # ------------------------------------------------------------- 会话内部
    async def _session(self):
        """一个完整的连接会话：CONNECT → CONNACK → 重订阅 → 读消息直到断开。"""
        try:
            await self._open()
        except Exception:
            self._close_writer()
            raise
        self.connected = True
        if self.on_connect:
            self.on_connect()
        for topic, qos in self._topics:
            await self._subscribe(topic, qos)
        ping = asyncio.create_task(self._ping_loop())
        try:
            await self._read_loop()
        finally:
            ping.cancel()
            self.connected = False
            self._close_writer()

    async def _open(self):
        """TCP 连接 + MQTT CONNECT 握手，校验 CONNACK。"""
        self._reader, self._writer = await asyncio.open_connection(
            self.server, self.port)
        # 协议名 "MQTT"(4)，级别 4，flags=0x02(clean session)，keepalive，client_id
        body = (b'\x00\x04MQTT\x04\x02'
                + struct.pack('>H', self.keepalive)
                + _encode_str(self.client_id))
        await self._send(b'\x10' + _encode_varint(len(body)) + body)
        resp = await self._read(4)        # CONNACK 固定 4 字节：20 02 rc rc
        if resp[:2] != b'\x20\x02' or resp[2] != 0 or resp[3] != 0:
            raise MQTTError('CONNACK 异常: %r' % resp)

    async def _subscribe(self, topic: str, qos: int) -> None:
        pid = 1
        body = struct.pack('>H', pid) + _encode_str(topic) + bytes([qos])
        await self._send(b'\x82' + _encode_varint(len(body)) + body)
        # SUBACK 随后到达，由 _read_loop 收到后忽略（kind == 8）

    async def _ping_loop(self):
        """keepalive 心跳：umqtt 需要手动 ping，这里按 keepalive/2 自动发。"""
        while True:
            await asyncio.sleep(self.keepalive / 2)
            try:
                await self._send(b'\xc0\x00')     # PINGREQ
            except Exception:
                return                            # 连接已坏，等读循环报错

    # ------------------------------------------------------------- 收发原语
    async def _send(self, buf: bytes) -> None:
        self._writer.write(buf)                   # 不 yield → 整帧原子入缓冲
        await self._writer.drain()

    async def _read(self, n: int) -> bytes:
        data = b''
        while len(data) < n:
            chunk = await self._reader.read(n - len(data))
            if not chunk:
                raise MQTTError('对端关闭连接')
            data += chunk
        return data

    async def _read_varint(self) -> int:
        value = 0
        mult = 1
        for _ in range(4):
            b = (await self._read(1))[0]
            value += (b & 0x7F) * mult
            if not (b & 0x80):
                return value
            mult *= 128
        raise MQTTError('剩余长度编码非法')

    def _close_writer(self):
        try:
            if self._writer is not None:
                self._writer.close()
        except Exception:
            pass
        self._writer = None

    # ------------------------------------------------------------- 读消息
    async def _read_loop(self):
        while True:
            b0 = (await self._read(1))[0]
            rem = await self._read_varint()
            data = await self._read(rem) if rem else b''
            kind = b0 >> 4
            if kind == 3:                 # PUBLISH
                await self._on_publish(b0, data)
            elif kind == 8:               # SUBACK
                pass
            elif kind == 13:              # PINGRESP
                pass
            elif kind == 14:              # 服务端主动 DISCONNECT
                raise MQTTError('broker DISCONNECT')
            # PUBACK/PUBREC/PUBCOMP（QoS1/2 上行未用）直接忽略

    async def _on_publish(self, b0: int, data: bytes):
        qos = (b0 >> 1) & 0x03
        if qos in (2, 3):
            return                        # QoS2/保留值：最小客户端不支持，整帧丢弃防错解析
        tlen = struct.unpack('>H', data[:2])[0]
        topic = data[2:2 + tlen].decode('utf-8')
        off = 2 + tlen
        if qos == 1:                      # 下行意外带 QoS1：回 PUBACK 防失步
            pid = data[off:off + 2]
            off += 2
            await self._send(b'\x40\x02' + pid)
        payload = data[off:]
        if self.on_message:
            self.on_message(topic, payload)
