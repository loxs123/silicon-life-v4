# 目标 : 

# 约束 : 人情味
# 

from .hooks import HOOKS
from .info import Info

class Decision:
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
        cur_info = Info(queues=self.queues)  # ★ 每轮重置
        for hook in self.hooks: # 每次调用一次模型
            hook(cur_info)
