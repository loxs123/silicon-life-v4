"""飞书网关 worker：长连接收消息 → _sub/feishu 入队；消费 _pub/feishu → 调 API 发出。

载荷格式见 core/queues.md。只收发，不做决策。
"""

from __future__ import annotations

import base64
import io
import json
import threading
from queue import Queue

from ..config import (FEISHU_APP_ID, FEISHU_APP_SECRET, FEISHU_DEFAULT_CHAT_ID,
                      QUEUE_FEISHU_PUB, QUEUE_FEISHU_SUB)

# lark-oapi 惰性导入：一万多个子模块，import 一次约 10 秒，放到 run() 里
_lark = None
_LARK_IMPORT_ERR = None
CreateImageRequest = CreateImageRequestBody = None
CreateMessageRequest = CreateMessageRequestBody = None


def _load_lark():
    """导入 lark_oapi（只导一次）；成功 True，失败 False。"""
    global _lark, _LARK_IMPORT_ERR
    global CreateImageRequest, CreateImageRequestBody
    global CreateMessageRequest, CreateMessageRequestBody
    if _lark is not None or _LARK_IMPORT_ERR is not None:
        return _lark is not None
    try:
        import lark_oapi
        from lark_oapi.api.im.v1 import (
            CreateImageRequest, CreateImageRequestBody,
            CreateMessageRequest, CreateMessageRequestBody,
        )
        _lark = lark_oapi
    except Exception as e:  # noqa: E722  ImportError 或 SDK 版本缺符号都算
        _LARK_IMPORT_ERR = e
    return _lark is not None


def _attr(obj, name, default=''):
    """取模型属性；SDK 版本不同缺字段时返回 default，不抛。"""
    try:
        v = getattr(obj, name)
    except Exception:
        return default
    return v if v is not None else default


def _resp_ok(resp):
    try:
        return bool(resp.success())
    except Exception:
        try:
            return int(_attr(resp, 'code', 1)) == 0
        except Exception:
            return False


def _resp_err(resp):
    try:
        return 'code=%s msg=%s' % (_attr(resp, 'code'), _attr(resp, 'msg'))
    except Exception:
        return str(resp)[:200]


def _sender_text(sender):
    """尽力取发送者标识（open_id / user_id / …），取不到给空串。"""
    for path in (('id',), ('sender_id', 'open_id'), ('sender_id', 'user_id'),
                 ('sender_id', 'union_id')):
        try:
            cur = sender
            for p in path:
                cur = getattr(cur, p)
            if cur:
                return str(cur)
        except Exception:
            continue
    return ''


class FeishuWorker:
    def __init__(self, queues: dict[str, Queue], stop_token=None,
                 app_id=None, app_secret=None, default_chat_id=None):
        self.queues = queues
        self.stop_token = stop_token
        self.app_id = app_id if app_id is not None else FEISHU_APP_ID
        self.app_secret = (app_secret if app_secret is not None
                           else FEISHU_APP_SECRET)
        self._default_chat_id = (default_chat_id if default_chat_id is not None
                                 else FEISHU_DEFAULT_CHAT_ID)
        self._chat_id = ''     # 最近一次收到消息的会话，出站兜底用
        self._api = None       # lark HTTP client，惰性创建
        self._ws = None        # lark 长连接对象
        self._closing = False

    def _on_message(self, data):
        try:
            self._on_message0(data)
        except Exception as e:
            print('[Feishu] 消息处理异常[%s]: %s' % (type(e).__name__, e),
                  flush=True)

    def _on_message0(self, data):
        event = _attr(data, 'event')
        if not event:
            return
        sender = _attr(event, 'sender')
        if (_attr(sender, 'sender_type') or '') == 'app':
            return                        # 忽略机器人自己发的消息
        message = _attr(event, 'message')
        if not message:
            return
        message_id = _attr(message, 'message_id')
        chat_id = _attr(message, 'chat_id')
        mtype = _attr(message, 'message_type') or _attr(message, 'msg_type')
        if chat_id:
            self._chat_id = chat_id       # 记住最近会话（出站兜底）

        raw = _attr(message, 'content')   # SDK 给的是 JSON 字符串
        content = {}
        if isinstance(raw, str):
            try:
                content = json.loads(raw or '{}')
            except Exception:
                content = {}
        elif isinstance(raw, dict):
            content = raw

        sender_name = _sender_text(sender)

        if mtype == 'text':
            text = (content.get('text') or '').strip()
            if not text:
                return
            print('[Feishu] 收到文字(%s): %s' % (sender_name or '?',
                                               text[:80]), flush=True)
            self.queues[QUEUE_FEISHU_SUB].put({
                'feishu': True,
                'text': text,
                'message_id': message_id,
                'chat_id': chat_id,
                'sender': sender_name,
            })
        elif mtype == 'image':
            image_key = (content.get('image_key') or '').strip()
            if not image_key:
                return
            data = self._image_base64(image_key)
            print('[Feishu] 收到图片(%s): key=%s %s' % (
                sender_name or '?', image_key,
                '%dB base64' % len(data) if data else '（下载失败）'),
                flush=True)
            payload = {
                'feishu': True,
                'type': 'image',
                'image_key': image_key,
                'message_id': message_id,
                'chat_id': chat_id,
                'sender': sender_name,
            }
            if data:
                payload['data'] = data
            self.queues[QUEUE_FEISHU_SUB].put(payload)
        else:
            print('[Feishu] 忽略消息类型: %s' % mtype, flush=True)

    def _send_out(self, msg):
        """发一条出站消息：载荷 chat_id → 最近入站会话 → config 兜底。"""
        if not isinstance(msg, dict):
            print('[Feishu] 忽略未知出站消息: %r' % (msg,), flush=True)
            return

        text = str(msg.get('text') or '').strip()
        img_b64 = msg.get('img') or ''
        if not text and not img_b64:
            print('[Feishu] 忽略未知出站 dict: %s' % str(msg)[:120], flush=True)
            return

        chat_id = (str(msg.get('chat_id') or '').strip()
                   or self._chat_id
                   or str(self._default_chat_id or '').strip())
        if not chat_id:
            print('[Feishu] 发送失败: 无 chat_id、无最近会话、'
                  'config.FEISHU_DEFAULT_CHAT_ID 也为空', flush=True)
            return

        if text:
            print('[Feishu] 发文字到会话(%s): %s' % (chat_id, text[:80]),
                  flush=True)
            self._send_text_to_chat(chat_id, text)
            return

        jpg = base64.b64decode(img_b64)
        print('[Feishu] 发图片到会话(%s): %dB' % (chat_id, len(jpg)), flush=True)
        self._send_image_to_chat(chat_id, jpg)

    def _api_client(self):
        """惰性构建 lark HTTP client（tenant token 由 SDK 管理）。"""
        if self._api is None:
            b = (_lark.Client.builder()
                 .app_id(self.app_id)
                 .app_secret(self.app_secret))
            domain = getattr(_lark, 'Domain', None)
            if domain is not None:      # 默认国内飞书；Lark 国际版改成 Domain.Lark
                try:
                    b = b.domain(domain.Feishu)
                except Exception:
                    pass
            try:
                b = b.log_level(_lark.LogLevel.WARN)
            except Exception:
                pass
            self._api = b.build()
        return self._api

    def _image_base64(self, image_key):
        """按 image_key 下载图片转 base64；拿不到返回空串。"""
        try:
            from lark_oapi.api.im.v1 import GetImageRequest
            req = GetImageRequest.builder().image_key(image_key).build()
            resp = self._api_client().im.v1.image.get(req)
            if getattr(resp, 'code', 1) == 0 and getattr(resp, 'file', None):
                return base64.b64encode(resp.file.read()).decode('ascii')
            print('[Feishu] 图片下载失败: %s（%s）'
                  % (image_key, _resp_err(resp)), flush=True)
        except Exception as e:
            print('[Feishu] 图片下载异常[%s]: %s（%s）'
                  % (type(e).__name__, e, image_key), flush=True)
        return ''

    def _send_text_to_chat(self, chat_id, text):
        """主动给会话发一条文字（im.v1.message.create）。"""
        req = (CreateMessageRequest.builder()
               .receive_id_type('chat_id')
               .request_body(CreateMessageRequestBody.builder()
                             .receive_id(chat_id)
                             .msg_type('text')
                             .content(json.dumps({'text': text},
                                                 ensure_ascii=False))
                             .build())
               .build())
        resp = self._api_client().im.v1.message.create(req)
        if not _resp_ok(resp):
            print('[Feishu] 发文字失败: %s' % _resp_err(resp), flush=True)

    def _upload_image(self, jpeg_bytes):
        """上传图片（image_type=message）→ image_key；失败返回空串。"""
        req = (CreateImageRequest.builder()
               .request_body(CreateImageRequestBody.builder()
                             .image_type('message')
                             .image(io.BytesIO(jpeg_bytes))
                             .build())
               .build())
        resp = self._api_client().im.v1.image.create(req)
        if not _resp_ok(resp):
            print('[Feishu] 图片上传失败: %s' % _resp_err(resp), flush=True)
            return ''
        try:
            return _attr(resp.data, 'image_key')
        except Exception:
            return ''

    def _send_image_to_chat(self, chat_id, jpeg_bytes):
        """上传图片并主动发给会话。"""
        key = self._upload_image(jpeg_bytes)
        if not key:
            return
        req = (CreateMessageRequest.builder()
               .receive_id_type('chat_id')
               .request_body(CreateMessageRequestBody.builder()
                             .receive_id(chat_id)
                             .msg_type('image')
                             .content(json.dumps({'image_key': key}))
                             .build())
               .build())
        resp = self._api_client().im.v1.message.create(req)
        if not _resp_ok(resp):
            print('[Feishu] 发图到会话失败: %s' % _resp_err(resp), flush=True)

    def _start_receiver(self):
        """daemon 线程里跑飞书长连接（阻塞），断线由 SDK 自动重连。"""

        def _run():
            try:
                handler = (_lark.EventDispatcherHandler
                           .builder('', '')          # (encrypt_key, verification_token)
                           .register_p2_im_message_receive_v1(self._on_message)
                           .build())
                ws_cls = _attr(getattr(_lark, 'ws', None), 'Client')
                if ws_cls:
                    self._ws = ws_cls(app_id=self.app_id,      # lark-oapi 2.x
                                      app_secret=self.app_secret,
                                      event_handler=handler)
                    self._ws.start()
                else:
                    self._api_client().start(handler)          # lark-oapi 1.x
            except Exception as e:
                print('[Feishu] 长连接异常退出[%s]: %s'
                      % (type(e).__name__, e), flush=True)
            finally:
                print('[Feishu] 长连接已停止', flush=True)

        t = threading.Thread(target=_run, name='eq12-feishu-ws', daemon=True)
        t.start()

    def run(self):
        """自检 → 起长连接线程（收）→ 阻塞消费 _pub/feishu（发）。"""
        missing = [k for k in (QUEUE_FEISHU_SUB, QUEUE_FEISHU_PUB)
                   if k not in self.queues]
        if missing:
            print('[Feishu] 缺少内部队列 %s：请在 main_loop.py 里创建'
                  % missing, flush=True)
            return
        if not (self.app_id and self.app_secret):
            print('[Feishu] 警告: 未设置 FEISHU_APP_ID / FEISHU_APP_SECRET，'
                  '飞书收发不可用（见 set_dashscope_env.cmd）', flush=True)
            return
        print('[Feishu] 正在加载 lark-oapi（上万个子模块，本机约 10 秒）…',
              flush=True)
        if not _load_lark():
            print('[Feishu] lark-oapi 不可用，飞书 worker 不启动'
                  '（pip install lark-oapi；原因为 %s）'
                  % _LARK_IMPORT_ERR, flush=True)
            return
        print('[Feishu] FeishuWorker 已启动'
              '（收→入队 %s，发←消费 %s）' % (QUEUE_FEISHU_SUB, QUEUE_FEISHU_PUB),
              flush=True)
        try:
            self._api_client()          # 提前暴露建 client 的配置错误
        except Exception as e:
            print('[Feishu] lark client 构建失败[%s]: %s'
                  % (type(e).__name__, e), flush=True)
            return
        self._start_receiver()
        try:
            while not self._closing:
                item = self.queues[QUEUE_FEISHU_PUB].get()   # 阻塞等出站消息
                if self.stop_token is not None and item is self.stop_token:
                    break
                try:
                    self._send_out(item)
                except Exception as e:
                    print('[Feishu] 发送失败[%s]: %s'
                          % (type(e).__name__, e), flush=True)
        finally:
            self.close()

    def close(self):
        """幂等收尾：停长连接 / HTTP client。"""
        self._closing = True
        for attr_name in ('_ws', '_api'):
            obj = getattr(self, attr_name, None)
            if obj is None:
                continue
            try:
                stop = getattr(obj, 'stop', None)
                if callable(stop):
                    stop()
            except Exception:
                pass
