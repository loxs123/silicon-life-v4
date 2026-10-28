
# 设计原则

- 一切皆hook
- 模型可见 = 已落日志
- one token prediction 做判别


# 日志
- `hooks/logs/`：每天一个文件 `YYYY-MM-DD.log`，**一行一个操作**，只追加
- `hooks/memory/`、`hooks/skills/`、`hooks/states/`：每天一个文件夹；第二天从最近一天（或 `seed/`）复制过来接着改
- 细节（格式、日切、记什么、API、落地清单）见 `core/log.md`

# 消息
- 延迟消息（已实现：`workers/delay_worker.py` —— 投 `_pub/delay` 记一件事，
  到点它把"15 分钟之前你让我…"推进 `_sub/delay` / `asr`；协议见 `core/queues.md`）

还需要三个元功能

1. SKILL CREATOR 创建skill
2. GOAL CHECKER  检查目标是否完成
3. GOAL ADJUSTOR 目标调整 输入 高层目标/当前状态/既定下一个子目标 输出 调整后的子目标

提出目标树的概念，所有除了叶子结点之外，都是目标，从头到尾一次执行完所有的叶子节点，也就是执行完所有的原子动作，我们就会完成这个根节点的目标


制定goal -> 创建skill -> 完成goal(多轮交互) -> 制定下一个goal -> ...
                                          (异步)-> 创建memory
