"""
DelayWorker —— 延迟消息：到点把「你之前让我做的事」推进 _sub/delay
====================================================================

「15 分钟之后提醒我喝水」不能在 hook 里 sleep（会拖死 brain 主循环），交给本
worker 记着；到点它往 _sub/delay 推一条消息：

    _pub/delay 投：{'text': '提醒我喝水', 'in': 900}      # 900 秒后到点
    _sub/delay 出：{'text': '15 分钟之前你让我提醒我喝水，现在到点了，你来接着办。',
                   'in': 900, 'due_at': <unix秒>, 'fired_at': <unix秒>}

格式固定，不做校验：投错（缺键、类型不对）就在 worker 线程里抛异常，不兜底。
除了 _pub/delay 和 _sub/delay 这两条队列，本 worker 不碰任何别的东西。

主循环很土：每轮先 sleep DELAY_POLL_S → 非阻塞取空 _pub/delay → 把到点的推到
_sub/delay → 下一轮。所以到点精度就是这个量级（提醒类场景够用）。没有停机哨兵：
线程是 daemon，随进程一起结束。

依赖：纯标准库。
"""

from __future__ import annotations

import queue
import time
from queue import Queue

from ..config import (DELAY_ECHO_TEMPLATE, DELAY_POLL_S, QUEUE_DELAY_PUB,
                      QUEUE_DELAY_SUB)


def format_ago(seconds):
    """秒数 -> '刚刚' / '15 分钟之前' / '2 小时之前' / '3 天之前'。"""
    if seconds < 60:
        return '刚刚'
    if seconds < 3600:
        return '%d 分钟之前' % (seconds // 60)
    if seconds < 86400:
        return '%d 小时之前' % (seconds // 3600)
    return '%d 天之前' % (seconds // 86400)


class DelayWorker:
    """消费 _pub/delay 的 {'text','in'}，到点往 _sub/delay 推那句话。"""

    def __init__(self, queues: dict[str, Queue]):
        self.queues = queues
        self.items = []            # 待办：[{'text', 'in', 'due_at'}]

    def run(self):
        print('[Delay] 已启动（投递←%s，到期→%s）'
              % (QUEUE_DELAY_PUB, QUEUE_DELAY_SUB), flush=True)
        while True:
            time.sleep(DELAY_POLL_S)  # 睡一会儿再看一眼，平时不占 CPU
            while True:               # 把队列里的投递一次取干净（不阻塞）
                try:
                    item = self.queues[QUEUE_DELAY_PUB].get_nowait()
                except queue.Empty:
                    break
                self._add(item)
            self._fire()              # 到点的都推出去

    def _add(self, item):
        """记下一条待办：{'text': …, 'in': 秒}。"""
        self.items.append({'text': item['text'], 'in': item['in'],
                           'due_at': time.time() + item['in']})
        print('[Delay] 待办 %d 条：%s 秒后「%s」'
              % (len(self.items), item['in'], item['text']), flush=True)

    def _fire(self):
        """到点的都推到 _sub/delay：一条「多久之前你让我做什么」的消息。"""
        now = time.time()
        for entry in [e for e in self.items if e['due_at'] <= now]:
            self.items.remove(entry)
            text = DELAY_ECHO_TEMPLATE.format(ago=format_ago(entry['in']),
                                              text=entry['text'])
            self.queues[QUEUE_DELAY_SUB].put({'text': text, 'in': entry['in'],
                                              'due_at': entry['due_at'],
                                              'fired_at': now})
            print('[Delay] 到期 → %s: %s' % (QUEUE_DELAY_SUB, text), flush=True)
