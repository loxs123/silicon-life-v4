"""延迟消息：到点把之前让做的事推进 _sub/delay。"""

from __future__ import annotations

import queue
import time
from queue import Queue

from ..config import (DELAY_ECHO_TEMPLATE, DELAY_POLL_S, QUEUE_DELAY_PUB,
                      QUEUE_DELAY_SUB)


def format_ago(seconds):
    if seconds < 60:
        return '刚刚'
    if seconds < 3600:
        return '%d 分钟之前' % (seconds // 60)
    if seconds < 86400:
        return '%d 小时之前' % (seconds // 3600)
    return '%d 天之前' % (seconds // 86400)


class DelayWorker:
    def __init__(self, queues: dict[str, Queue]):
        self.queues = queues
        self.items = []            # 待办：[{'text', 'in', 'due_at'}]

    def run(self):
        print('[Delay] 已启动（投递←%s，到期→%s）'
              % (QUEUE_DELAY_PUB, QUEUE_DELAY_SUB), flush=True)
        while True:
            time.sleep(DELAY_POLL_S)
            while True:
                try:
                    item = self.queues[QUEUE_DELAY_PUB].get_nowait()
                except queue.Empty:
                    break
                self._add(item)
            self._fire()

    def _add(self, item):
        self.items.append({'text': item['text'], 'in': item['in'],
                           'due_at': time.time() + item['in']})
        print('[Delay] 待办 %d 条：%s 秒后「%s」'
              % (len(self.items), item['in'], item['text']), flush=True)

    def _fire(self):
        now = time.time()
        for entry in [e for e in self.items if e['due_at'] <= now]:
            self.items.remove(entry)
            text = DELAY_ECHO_TEMPLATE.format(ago=format_ago(entry['in']),
                                              text=entry['text'])
            self.queues[QUEUE_DELAY_SUB].put({'queue': QUEUE_DELAY_SUB, 'type': 'text',
                                              'text': text, 'in': entry['in'],
                                              'due_at': entry['due_at'],
                                              'fired_at': now})
            print('[Delay] 到期 → %s: %s' % (QUEUE_DELAY_SUB, text), flush=True)
