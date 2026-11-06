
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


# 已实现：白天最小闭环（dream 暂不做）

`Pipeline.process()` 一直跑 hook，直到产生具体动作；每个 hook 一次调用最多问一次模型：

| hook | 做什么 |
|---|---|
| `plan` | 今天还没有 goal → 建根目标 `goal_0001`「今天还没有计划」，指定用 `plan` 技能拆它（不调模型） |
| `goal` | 非阻塞收消息：`asr` / `_sub/feishu` / `_sub/delay` 每条建一个新的根 goal；`_sub/desktop` / `sub/leg` / `sub/eye` 的回执记进日志。选目标：外来消息先办，再办计划，走到第一个没完成的叶子；子目标全完成的父目标直接完成。**GOAL CHECKER**：动作做过、还没判过 → 一个字（是 / 否）判完成 |
| `skill` | 选技能（只回编号）→ 没有合适的就用 `skill_creator` 造一个（**SKILL CREATOR**）→ 执行：`子目标` 类按 `protocols-json/sub_goals.json` 出子 goal，`原子动作` 类按 `protocols-json/atom_actions.json` 投队列，置 `action` 结束这一轮 |
| `memory` | 任务级 goal（外来消息的根、计划下的时间段）完成后，用 `memory_creator` 写一条记忆，最近 10 条拼进执行技能时的系统提示 |

- 存储全按 `protocols-json/`：`states/<今天>/goal_NNNN.json`、`skills/<今天>/skill_NNNN.json`、`memory/<今天>/memory_NNNN.json`，经 `tools/loader.py` 读写（当天目录不存在就从最近一天 / seed 复制，states 不往下带），新内容先过 `tools/checker.py`
- 日志：`tools/log.py`，`hooks/logs/<今天>.log` 一行一个 JSON；goal 的经过、选了哪个技能、回执都从这里读（模型可见 = 已落日志）
- 不阻塞：回执异步进日志。投了会回执的动作（桌面 / 腿 / 眼）后，回执没到之前这个 goal 先不判，最多 10 秒
- 护栏：一个 goal 最多 8 次动作、模型输出坏 3 次放弃、最多拆 4 层
- 截图 / 照片存 `eq12_server/cache/`，`<img>` 写这个路径转发
- 测试：`python tests/test_brain.py`、`python tests/test_plan.py`（假模型，不联网）
