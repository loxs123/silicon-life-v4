"""
BrainWorker —— "大脑"器官
"""

import os
import re
import time
from queue import Queue

from ..core.pipeline import Pipeline

class BrainWorker:
    """消费 asr 队列的文本,流式调用模型,把完整句子逐句投进 tts 队列。"""

    def __init__(self, queues: dict[str, Queue]):
        self.queues = queues

    def run(self):
        p = Pipeline(self.queues)      # hooks 在 Pipeline.__init__ 里注册好了
        while True:
            p.process()
            time.sleep(0.1)
