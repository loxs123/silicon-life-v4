"""
FeishuWorker —— 飞书消息网关 worker（只收发消息，不做决策）
============================================================

eq12_server 进程内直连飞书 OpenAPI（WebSocket 长连接收事件、HTTPS 发消息），
**不经过**本地 MQTT broker（MQTT 只服务 ESP32 器官）。飞书收发各用一条内部
队列（在 main_loop 里与 asr/tts 同级创建；名称带 '_' 前缀表示纯内部队列，
不会被当作 MQTT 主题、也不会被 stop() 哨兵或专职发送线程接管）：

    _sub/feishu   收 / 入站：本 worker 收到飞书用户消息 → 打包成 dict 入队
                  （文字、图片都进；下游「大脑/桥接」从这里消费。决策统一在
                   brain，本 worker 不做 LLM 等任何决策 —— 骨架阶段只入队+打日志）
    _pub/feishu   发 / 出站：大脑/上游把出口消息放进此队列，
                  本 worker 消费并调用飞书 API 真正发出

队列载荷协议（沿用 v3 src/actors/feishu.py 的 mailbox 协议）：

    feishu -> 下游（_sub/feishu 队列里的 dict）：
        文字:  {'feishu': True, 'text': <str>, 'message_id': <str>,
                'chat_id': <str>, 'sender': <str>}
        图片:  {'feishu': True, 'type': 'image', 'image_key': <str>,
                'message_id': <str>, 'chat_id': <str>, 'sender': <str>}
                （图片本体要等视觉识别时才按 image_key 下载，骨架阶段只记录）

    上游 -> feishu（_pub/feishu 队列里的消息）：
        str  "[FEISHU]:<message_id>|<文字>"    → 在该消息下回复文字
        dict {'img': <base64 JPEG>, 'chat_id': <str>}   → 给会话主动发图
              （如 <cam> 拍照结果回传；chat_id 缺省时发给最近会话）

依赖：
    pip install lark-oapi        # 官方 SDK（长连接事件 + 消息/图片 API）

凭据（勿硬编码、勿提交仓库）：
    set_dashscope_env.cmd 里持久化环境变量 FEISHU_APP_ID / FEISHU_APP_SECRET
    （飞书自建应用凭据；tenant_access_token 由 SDK 自动获取/缓存/续期）

备注：
    - lark-oapi 是惰性导入的（_load_lark()）：它在模块顶部导一次要 ~10 秒
      （上万个子模块），所以只在 run() 里真连飞书时才导，不拖慢启动。
      未安装时本模块可正常 import，run() 打印提示并返回，其余 worker 不受影响。
    - 默认连接国内飞书（open.feishu.cn）；若用 Lark 国际版应用，需给 client
      显式指定 domain=lark.Domain.Lark。
"""

from __future__ import annotations

import base64
import io
import json
import os
import threading
from queue import Queue

SUB_QUEUE = '_sub/feishu'   # 收：收到消息入队（下游 brain/桥接 消费）
PUB_QUEUE = '_pub/feishu'   # 发：出站消息队列（本 worker 消费并发送）
FEISHU_PREFIX = '[FEISHU]:'  # 出站文字消息前缀（与 v3 一致）

# lark-oapi 官方 SDK：装不上/版本差异都不应拖垮 eq12_server。
# 这 SDK 是个生成式巨无霸（本机 10727 个子模块），import 一次约 10 秒 —— 所以
# 不在模块顶部导，改成 run() 里真要连飞书时才导：run() 跑在自己的线程里，
# 不会拖住启动；具体报错也挪到那里提示。
_lark = None
_LARK_IMPORT_ERR = None
CreateImageRequest = CreateImageRequestBody = None
CreateMessageRequest = CreateMessageRequestBody = None
ReplyMessageRequest = ReplyMessageRequestBody = None


def _load_lark():
    """惰性 import lark_oapi（只导一次）：成功返回 True，失败返回 False。"""
    global _lark, _LARK_IMPORT_ERR
    global CreateImageRequest, CreateImageRequestBody
    global CreateMessageRequest, CreateMessageRequestBody
    global ReplyMessageRequest, ReplyMessageRequestBody
    if _lark is not None or _LARK_IMPORT_ERR is not None:
        return _lark is not None
    try:
        import lark_oapi
        from lark_oapi.api.im.v1 import (
            CreateImageRequest, CreateImageRequestBody,
            CreateMessageRequest, CreateMessageRequestBody,
            ReplyMessageRequest, ReplyMessageRequestBody,
        )
        _lark = lark_oapi
    except Exception as e:  # noqa: E722  ImportError 或 SDK 版本缺符号都算
        _LARK_IMPORT_ERR = e
    return _lark is not None


def _attr(obj, name, default=''):
    """安全取模型属性：SDK 版本差异导致缺字段时不抛，返回 default。"""
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
    """尽力取发送者标识（open_id/user_id/…），取不到给空串。"""
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
    """飞书消息网关：长连接收消息 → _sub/feishu 入队；消费 _pub/feishu → 发出。

    stop_token 语义与其他 worker 一致（队列里出现它即退出主循环）；
    但 _pub/feishu、_sub/feishu 是 '_' 前缀内部队列，MainLoop.stop() 不会
    向它们投哨兵 —— 与消费内部 asr/tts 队列的 worker 一样随进程退出（daemon）。
    """

    # 类属性别名：main_loop.py 里是按 `FeishuWorker.SUB_QUEUE` 取队列名的，
    # 而队列名本身是上面的模块级常量（模块级那份照旧，外部直接 import 用）。
    SUB_QUEUE = SUB_QUEUE
    PUB_QUEUE = PUB_QUEUE

    def __init__(self, queues: dict[str, Queue], stop_token=None,
                 app_id=None, app_secret=None):
        self.queues = queues
        self.stop_token = stop_token
        # 凭据优先取环境变量（set_dashscope_env.cmd 持久化），可注入覆盖（测试用）
        self.app_id = (app_id if app_id is not None
                       else os.environ.get('FEISHU_APP_ID', ''))
        self.app_secret = (app_secret if app_secret is not None
                           else os.environ.get('FEISHU_APP_SECRET', ''))
        self._chat_id = ''     # 最近一次收到消息的会话（发图兜底目标，同 v3）
        self._api = None       # lark HTTP client（发消息用，惰性创建）
        self._ws = None        # lark 长连接对象（收事件用）
        self._closing = False

    # ============================ 收（事件回调 → _sub/feishu 入队） =========
    def _on_message(self, data):
        """lark 长连接事件回调（同步函数即可，SDK 自带线程调用）。

        只做一件事：把收到的文字/图片消息打包成 v3 协议 dict，
        放进 _sub/feishu 队列 + 打日志。任何异常只打印，不回抛（长连接线程不能死）。
        """
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
            self._chat_id = chat_id       # 记住最近会话（发图兜底目标）

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
            self.queues[SUB_QUEUE].put({
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
            print('[Feishu] 收到图片(%s): key=%s' % (sender_name or '?',
                                                    image_key), flush=True)
            self.queues[SUB_QUEUE].put({
                'feishu': True,
                'type': 'image',
                'image_key': image_key,
                'message_id': message_id,
                'chat_id': chat_id,
                'sender': sender_name,
            })
        else:
            print('[Feishu] 忽略消息类型: %s' % mtype, flush=True)

    # ============================ 发（消费 _pub/feishu 并调用 API） =========
    def _send_out(self, msg):
        """处理一条出站消息（文字回复 / 主动发图）。异常由 run() 兜底打印。"""
        if isinstance(msg, str) and msg.startswith(FEISHU_PREFIX):
            rest = msg[len(FEISHU_PREFIX):]
            mid, _, text = rest.partition('|')
            mid = mid.strip()
            text = text.strip()
            if mid and text:
                print('[Feishu] 回复文字: %s' % text[:80], flush=True)
                self._reply_text(mid, text)
            return
        if isinstance(msg, dict):
            img_b64 = msg.get('img') or ''
            if img_b64:
                chat_id = str(msg.get('chat_id') or '').strip() or self._chat_id
                if not chat_id:
                    print('[Feishu] 发图失败: 无 chat_id 且无最近会话', flush=True)
                    return
                jpg = base64.b64decode(img_b64)
                print('[Feishu] 发图片到会话(%s): %dB' % (chat_id, len(jpg)),
                      flush=True)
                self._send_image_to_chat(chat_id, jpg)
            else:
                print('[Feishu] 忽略未知出站 dict: %s'
                      % str(msg)[:120], flush=True)
            return
        print('[Feishu] 忽略未知出站消息: %r' % (msg,), flush=True)

    # ------------------------- lark HTTP 发送原语 --------------------------
    def _api_client(self):
        """惰性构建 lark HTTP client（tenant token 等由 SDK 自动管理）。"""
        if self._api is None:
            b = (_lark.Client.builder()
                 .app_id(self.app_id)
                 .app_secret(self.app_secret))
            # 默认国内飞书域；显式指明更稳（Lark 国际版改成 Domain.Lark）
            domain = getattr(_lark, 'Domain', None)
            if domain is not None:
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

    def _reply_text(self, message_id, text):
        """在该消息下回复文字（回复消息接口，SDK: im.v1.message.reply）"""
        req = (ReplyMessageRequest.builder()
               .message_id(message_id)
               .request_body(ReplyMessageRequestBody.builder()
                             .msg_type('text')
                             .content(json.dumps({'text': text},
                                                 ensure_ascii=False))
                             .build())
               .build())
        resp = self._api_client().im.v1.message.reply(req)
        if not _resp_ok(resp):
            print('[Feishu] 回复失败: %s' % _resp_err(resp), flush=True)

    def _upload_image(self, jpeg_bytes):
        """上传图片（用途=message）→ 返回 image_key；失败返回空串。"""
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
        """上传图片并主动发给会话（机器人推送，如 <cam> 拍照结果）"""
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

    # ============================ 长连接（收） =============================
    def _start_receiver(self):
        """在 daemon 线程里跑飞书长连接（阻塞）。断线 SDK 自动重连。"""

        def _run():
            try:
                handler = (_lark.EventDispatcherHandler
                           .builder('', '')          # (encrypt_key, verification_token)
                           .register_p2_im_message_receive_v1(self._on_message)
                           .build())
                ws_cls = _attr(getattr(_lark, 'ws', None), 'Client')
                if ws_cls:
                    # lark-oapi 2.x：独立 ws.Client 跑长连接
                    self._ws = ws_cls(app_id=self.app_id,
                                      app_secret=self.app_secret,
                                      event_handler=handler)
                    self._ws.start()
                else:
                    # lark-oapi 1.x：主 Client.start(handler) 即长连接
                    self._api_client().start(handler)
            except Exception as e:
                print('[Feishu] 长连接异常退出[%s]: %s'
                      % (type(e).__name__, e), flush=True)
            finally:
                print('[Feishu] 长连接已停止', flush=True)

        t = threading.Thread(target=_run, name='eq12-feishu-ws', daemon=True)
        t.start()

    # ============================ 主循环 / 生命周期 ========================
    def run(self):
        """自检 → 启动长连接线程（收）→ 阻塞消费 _pub/feishu（发）。"""
        missing = [k for k in (SUB_QUEUE, PUB_QUEUE) if k not in self.queues]
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
              '（收→入队 %s，发←消费 %s）' % (SUB_QUEUE, PUB_QUEUE), flush=True)
        try:
            self._api_client()          # 提前暴露建 client 的配置错误
        except Exception as e:
            print('[Feishu] lark client 构建失败[%s]: %s'
                  % (type(e).__name__, e), flush=True)
            return
        self._start_receiver()
        try:
            while not self._closing:
                item = self.queues[PUB_QUEUE].get()   # 阻塞等出站消息
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
        """幂等收尾：停长连接/HTTP client（进程退出时 daemon 线程也会被带走）。"""
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
