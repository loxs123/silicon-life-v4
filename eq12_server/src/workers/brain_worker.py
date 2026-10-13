"""
BrainWorker —— "大脑"器官
"""

import os
import re
import time
from queue import Queue

from ..core.dream import DreamPipeline
from ..core.pipeline import Pipeline

from ..config import DREAM_NIGHT_END, DREAM_NIGHT_START, DREAM_POLL_S


def is_night(now=None):
    """现在是不是 dream 时段。跨午夜也对（默认 23:00–07:00）。"""
    h = (now or time.localtime()).tm_hour
    if DREAM_NIGHT_START <= DREAM_NIGHT_END:
        return DREAM_NIGHT_START <= h < DREAM_NIGHT_END
    return h >= DREAM_NIGHT_START or h < DREAM_NIGHT_END


class BrainWorker:
    """白天跑 Pipeline，晚上跑 DreamPipeline —— 两条链互斥，不并发。"""

    def __init__(self, queues: dict[str, Queue]):
        self.queues = queues

    def run(self):
        pipeline = Pipeline(self.queues)      # hooks 在 Pipeline.__init__ 里注册好了
        dream = DreamPipeline(self.queues)    # 同上
        while True:
            if is_night():
                dream.run()           # 一整晚：内部循环，天亮返回
            else:
                pipeline.process()    # 白天：一轮
            time.sleep(0.1)
