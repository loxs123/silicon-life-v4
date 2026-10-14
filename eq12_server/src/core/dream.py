"""DreamPipeline —— 夜间链，与白天的 Pipeline 并列。

1. 优化记忆，暂定将记忆设置为单个markdown文件，文件中每个记忆带有时间
2. 优化系统，优化价值观等
3. 优化技能，进行技能的合并和优化（技能匹配方式、技能本身）
"""
import time
from .dream_hooks import HOOKS


class DreamPipeline:
    def __init__(self, queues):
        """
        queues 是 {队列名: queue.Queue}，和 Pipeline 收的是同一个字典。
        """
        self.queues = queues
        self.hooks = HOOKS
        # 整晚有效（对比 Pipeline.user_info 是每轮重置）
        self.state = {}

    def run(self):
        """睡一整晚：整条链反复跑，天亮就醒（返回）。

        白天 brain_worker 不会调这里 —— 互斥由调用方的 if/else 保证。
        """
        while is_night():
            for hook in self.hooks:
                hook(self) # 内部控制不能超过黑夜
            time.sleep(DREAM_POLL_S)
