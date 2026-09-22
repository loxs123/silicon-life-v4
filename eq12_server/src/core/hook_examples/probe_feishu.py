"""[测试] 等一条飞书消息，把它原样发回去。"""
from ...workers.feishu_worker import PUB_QUEUE, SUB_QUEUE


def probe_feishu(self):
    msg = self.queues[SUB_QUEUE].get()
    print('[brain] probe_feishu ← %s: %s' % (SUB_QUEUE, msg), flush=True)

    text = msg.get('text')
    if text:
        reply = '[FEISHU]:%s|%s' % (msg['message_id'], text)
        self.queues[PUB_QUEUE].put(reply)
        print('[brain] probe_feishu → %s: %s' % (PUB_QUEUE, reply), flush=True)
