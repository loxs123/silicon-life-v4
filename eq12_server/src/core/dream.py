"""DreamPipeline —— 夜间链，与白天的 Pipeline 并列。

分工是**时间上的**，不是优先级上的：

    白天（非 dream 时段）：只有 Pipeline 在跑
    晚上（dream 时段）   ：只有 DreamPipeline 在跑

两者永不同时执行，所以不需要抢占、异步发起、预算守卫这些东西 ——
整条链跑一遍就够了。（真要并发再补，现在不预支复杂度。）

hook 写法与 Pipeline 完全一致：一个文件 + 一个函数，第一参数是 self，
自己读 self.queues / self.state（见 core/architecture.md）。
"""
import time

DREAM_HOOKS = []      # 按顺序注册，不会自动发现（同 hooks/__init__.py 的约定）


class DreamPipeline:
    def __init__(self, queues):
        """
        queues 是 {队列名: queue.Queue}，和 Pipeline 收的是同一个字典。
        """
        self.queues = queues
        self.hooks = DREAM_HOOKS
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
