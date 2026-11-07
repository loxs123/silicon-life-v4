# 目标 : 

# 约束 : 人情味
# 

import time

from .hooks import HOOKS
from .info import Info

class Decision:
    info = Info()
    day = ''

    def __init__(self, queues):
        """
        inputs 是一个字典，输入的所有键是队列名:获取到的值
        """
        self.queues = queues
        self.hooks = HOOKS
    
    def process(self, ):
        """
        也需要一个回调自己的机制
        """
        today = time.strftime('%Y-%m-%d')
        Decision.queues = self.queues
        if Decision.day != today:
            Decision.day = today
            Decision.info.goals = []
            Decision.info.loaded = False
        info = Decision.info
        info.queues = self.queues
        while not info.actions:
            for hook in self.hooks: # 每次调用一次模型
                hook(info)
