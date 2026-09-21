"""
BrainWorker —— "大脑"器官
"""

import os
import re
import time
from queue import Queue

from ..core.pipeline import Pipeline

class BrainWorker:
    """消费 asr 队列的文本,流式调用模型,把完整句子逐句投进 tts 队列。

    stop_token 是主循环停机时投进 pub/*、sub/* 队列的 _STOP 哨兵对象;
    run() get() 到它即退出(不把它当业务文本),用于优雅停机。
    """

    def __init__(self, queues: dict[str, Queue]):
        self.queues = queues

    def run(self):
        p = Pipeline(queues)
        while True:
            p.process()
            time.sleep(0.1)
