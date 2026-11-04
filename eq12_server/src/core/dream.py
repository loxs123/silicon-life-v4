import time

from ..config import DREAM_NIGHT_END
from .dream_hooks import HOOKS


class DreamPipeline:
    def __init__(self, queues):
        self.queues = queues
        self.hooks = HOOKS

    def run(self):
        self.user_info = {}
        for hook in self.hooks:
            hook(self)
        now = time.localtime()
        target = time.mktime((now.tm_year, now.tm_mon, now.tm_mday,
                              DREAM_NIGHT_END, 0, 0, 0, 0, -1))
        secs = target - time.mktime(now)
        time.sleep(secs if secs > 0 else secs + 86400)
