# 目标 : 

# 约束 : 人情味
# 

from .hooks import HOOKS

class Pipeline:
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
        self.user_info = {}      # ★ 每轮重置
        while not self.user_info.get('action'): # 知道制定出具体的动作
            for hook in self.hooks: # 每次调用一次模型
                hook(self)                 # hook 的第一参数就是 self（见 core/architecture.md）
