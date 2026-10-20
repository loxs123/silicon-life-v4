"""DelayWorker 冒烟测试：不联网、不装任何 pip 依赖（纯标准库 + 假队列）。

跑法（在 eq12_server/ 目录下）：
    python tests/test_delay_worker.py

为什么能免依赖：import src.workers.delay_worker 会先执行 src/workers/__init__.py，
那里会连带 import pyautogui / dashscope / paho 这些可选依赖；本测试在导入前先用
一个只带 __path__ 的假包占住 sys.modules['src.workers']，于是只加载 delay_worker
自己（它只用标准库）。

覆盖：
  1. 文案：format_ago（'刚刚' / '15 分钟之前' / '2 小时之前' / '3 天之前'）
  2. 到期推送：{'text':…, 'in': 0.3} → _sub/delay 出那条消息（每 DELAY_POLL_S 轮询
     一次，所以要给几秒余量）；到期不重复推
  3. 投递格式是固定的：缺键就抛 KeyError（不兜底），进程不会假装收到了
"""
import os
import sys
import threading
import time
import types
from queue import Empty, Queue

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import src  # noqa: E402          # 命名空间包（src/ 下没有 __init__.py）

_workers_pkg = types.ModuleType('src.workers')
_workers_pkg.__path__ = [os.path.join(ROOT, 'src', 'workers')]
sys.modules['src.workers'] = _workers_pkg

from src.config import (DELAY_ECHO_TEMPLATE, DELAY_POLL_S,  # noqa: E402
                        QUEUE_DELAY_PUB, QUEUE_DELAY_SUB)
from src.workers.delay_worker import DelayWorker, format_ago  # noqa: E402


class Harness:
    """假 main_loop：只建 delay 那两条队列 + 起一个 DelayWorker 线程（daemon）。"""

    def __init__(self):
        self.queues = {QUEUE_DELAY_PUB: Queue(), QUEUE_DELAY_SUB: Queue()}
        self.worker = DelayWorker(self.queues)
        self.thread = threading.Thread(target=self.worker.run, daemon=True)
        self.thread.start()
        time.sleep(0.05)          # 等 worker 起跑（连上队列）

    def send(self, item):
        self.queues[QUEUE_DELAY_PUB].put(item)

    def take(self, timeout=8.0):
        """每 DELAY_POLL_S 轮询一次：注册等一轮、到点再等一轮，留够余量。"""
        return self.queues[QUEUE_DELAY_SUB].get(timeout=timeout)

    def take_quiet(self, timeout=0.4):
        """超时返回 None（用于断言"不该再来消息"）。"""
        try:
            return self.queues[QUEUE_DELAY_SUB].get(timeout=timeout)
        except Empty:
            return None


def test_text():
    assert format_ago(0.3) == '刚刚'
    assert format_ago(45) == '刚刚'
    assert format_ago(900) == '15 分钟之前'
    assert format_ago(5400) == '1 小时之前'
    assert format_ago(86400 * 3 + 60) == '3 天之前'
    assert DELAY_ECHO_TEMPLATE.format(ago=format_ago(900),
                                      text='提醒我喝水') == \
        '15 分钟之前你让我提醒我喝水，现在到点了，你来接着办。'


def test_schedule_and_fire():
    h = Harness()
    before = time.time()
    h.send({'text': '提醒我喝水', 'in': 0.3})
    msg = h.take()
    assert msg['text'] == '刚刚你让我提醒我喝水，现在到点了，你来接着办。', msg
    assert msg['in'] == 0.3, msg
    assert msg['due_at'] - before >= 0.2, msg         # 真的记成 0.3s 后
    assert msg['fired_at'] >= msg['due_at']
    assert msg['fired_at'] - msg['due_at'] <= DELAY_POLL_S + 1.0, msg
    assert h.take_quiet() is None, '到期消息不该重复推送'


def test_bad_payload_raises():
    """格式固定：缺 text 就当 KeyError 抛出去（不校验、不兜底）。"""
    w = DelayWorker({QUEUE_DELAY_PUB: Queue(), QUEUE_DELAY_SUB: Queue()})
    for bad in ({'in': 5}, 'not a dict'):
        try:
            w._add(bad)
        except (KeyError, TypeError):
            pass
        else:
            raise AssertionError('应当直接报错: %r' % (bad,))
    assert w.items == [], '坏载荷不该进待办'


def main():
    test_text()
    test_schedule_and_fire()
    test_bad_payload_raises()
    print('DELAY WORKER TEST PASS: 文案 / 到期推送 / 固定格式 全通过')


if __name__ == '__main__':
    main()
