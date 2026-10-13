"""[测试] 等一条飞书消息，把它原样发回去。"""
from src.config import QUEUE_FEISHU_PUB, QUEUE_FEISHU_SUB


def probe_feishu(self):
    msg = self.queues[QUEUE_FEISHU_SUB].get()
    print('[brain] probe_feishu ← %s: %s' % (QUEUE_FEISHU_SUB, msg), flush=True)

    text = msg.get('text')
    if text:
        out = {'text': text, 'chat_id': msg.get('chat_id') or ''}
        self.queues[QUEUE_FEISHU_PUB].put(out)
        print('[brain] probe_feishu → %s: %s' % (QUEUE_FEISHU_PUB, out),
              flush=True)
