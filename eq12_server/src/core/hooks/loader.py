import json
import queue
import time
import re
from xml.sax.saxutils import escape

from ...config import (QUEUE_ASR, QUEUE_DELAY_SUB, QUEUE_DESKTOP_SUB,
                       QUEUE_EYE_SUB, QUEUE_FEISHU_SUB, QUEUE_LEG_SUB)
from ..info import Info
from .tools import log

TOPICS = (QUEUE_ASR, QUEUE_FEISHU_SUB, QUEUE_DELAY_SUB, QUEUE_DESKTOP_SUB,
          QUEUE_LEG_SUB, QUEUE_EYE_SUB)
FIELDS = ('queue', 'type', 'text', 'message_id', 'chat_id', 'sender', 'image_key',
          'data', 'in', 'due_at', 'fired_at', 'width', 'height', 'size', 'fmt',
          'time', 'command')


def _drain(q):
    items = []
    while True:
        try:
            items.append(q.get_nowait())
        except queue.Empty:
            return items


def _norm(name, item):
    if hasattr(item, 'payload'):
        item = item.payload
    if isinstance(item, bytes):
        try:
            item = json.loads(item.decode('utf-8'))
        except Exception:
            item = item.decode('utf-8', 'replace')
    if not isinstance(item, dict):
        item = {'text': item}
    item = dict(item)
    item['queue'] = name
    item.setdefault('type', 'text' if 'text' in item else 'photo')
    if isinstance(item.get('time'), (int, float)):
        item['time'] = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(item['time']))
    return '<queue_msg>%s</queue_msg>' % ''.join(
        '<%s>%s</%s>' % (k, escape(json.dumps(item[k], ensure_ascii=False)
                                   if isinstance(item[k], (dict, list))
                                   else str(item[k])), k)
        for k in FIELDS if k in item)


def load_goals():
    today = time.strftime('%Y-%m-%d')

    print(today)

def hook(cur_info: Info):
    for name in TOPICS:
        q = cur_info.queues.get(name)
        if q is None:
            continue
        for item in _drain(q):
            msg = _norm(name, item)
            log.write('queue-msg', msg)
            cur_info.context.append(msg)

if __name__ == '__main__':
    import types

    for name, item in (
            ('asr', '你好呀'),
            ('_sub/feishu', {'feishu': True, 'text': '你好', 'message_id': 'om_1',
                             'chat_id': 'oc_1', 'sender': 'ou_1'}),
            ('_sub/feishu', {'feishu': True, 'type': 'image', 'image_key': 'img_1',
                             'data': 'QUJDREVGR0hJSktM', 'message_id': 'om_1',
                             'chat_id': 'oc_1', 'sender': 'ou_1'}),
            ('_sub/delay', {'text': '15 分钟之前你让我提醒我喝水，现在到点了，你来接着办。',
                            'in': 900, 'due_at': 1793000000.5, 'fired_at': 1793000002.3}),
            ('_sub/desktop', {'type': 'screen', 'time': 1793000000, 'size': 12,
                              'width': 1920, 'height': 1080, 'fmt': 'jpeg',
                              'data': 'QUJDREVGR0hJSktM'}),
            ('_sub/desktop', {'type': 'done', 'time': 1793000000,
                              'command': {'type': 'screenshot'}}),
            ('sub/leg', types.SimpleNamespace(topic=b'sub/leg',
                                              payload=b'done:forward,50,2')),
            ('sub/eye', types.SimpleNamespace(topic=b'sub/eye', payload=(
                '{"type":"photo","time":"2026-11-05 12:00:00","size":3,'
                '"width":320,"height":240,"data":"AAAA"}').encode())),
            ('asr', ''),
            ('_sub/feishu', {}),
            ('sub/leg', types.SimpleNamespace(topic=b'sub/leg', payload=b'not json')),
    ):
        print(_norm(name, item))