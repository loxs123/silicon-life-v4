# 

class Pipeline:
    def __init__(self, queues):
        """
        inputs 是一个字典，输入的所有键是队列名:获取到的值
        """
        self.queues = queues
        self.hooks = []
        self.user_info = {}
        self.cache_dir = ''
    
    def process(self, ):
        """
        也需要一个回调自己的机制
        """
        for hook in self.hooks:
            hook()
        return self.user_info['output']