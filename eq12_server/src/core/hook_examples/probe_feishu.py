"""[测试] 等一条飞书消息，把它原样发回去。"""
from src.config import FEISHU_PREFIX, QUEUE_FEISHU_PUB, QUEUE_FEISHU_SUB


def probe_feishu(self):
    msg = self.queues[QUEUE_FEISHU_SUB].get()
    print('[brain] probe_feishu ← %s: %s' % (QUEUE_FEISHU_SUB, msg), flush=True)

    text = msg.get('text')
    if text:
        reply = FEISHU_PREFIX + msg['message_id'] + '|' + text
        self.queues[QUEUE_FEISHU_PUB].put(reply)
        print('[brain] probe_feishu → %s: %s' % (QUEUE_FEISHU_PUB, reply),
              flush=True)
