# 论文摘要（重写版）

> 上一版的问题：通篇是"协议粒度决定自进化粒度"这类自造命题，读者读完仍不知道**这个系统是什么、技能长什么样、到底改了什么**。
> 这一版改成：**先讲具体的系统 → 举个具体技能 → 说清哪里坏 → 说清改法 → 说清怎么验**。
> 系统尚未跑出数据（`skill.py` / `goal.py` 为空，`optimize_skill.py` 是两个 TODO），因此结果处留占位符。

---

## 0. 三句话版本（电梯陈述，先给自己对齐用）

> 我做了一个每天 24 小时在跑的智能体：它只会两件事——**把目标拆得更细**，或者**真的做一个动作**（说话、发飞书、点鼠标、看摄像头）。
>
> 学到的东西它存成 markdown「技能」。但原来是提示词、步骤、坑、例子全塞在一个正文里，夜里让模型自己改进这些技能时**改不动**——不知道该改哪一行；也**判不了**——不知道这次成功是哪一步起了作用。
>
> 所以我给技能定了一套格式：一个技能只能做两件事之一，每一步要写清做什么、期望看到什么、失败了怎么办、这条经验来自哪天日志。然后用**一周前的历史日志回放**来验收改进：跑得比现版本好才采纳。

---

## 1. 直白版摘要（读者 30 秒能懂；适合预印本、博客、口头报告）

### 中文

**摘要**

我们做了一个 24 小时运行的智能体：一块 ESP32 当身体（听、说、看、动、表情），一台小主机当大脑（理解、决策、记忆）。它每天只有两种操作——把当前目标拆成更细的子目标，或者执行一个真实动作。学着做过的事，它存成 markdown 文件，叫「技能」：一个技能就是「什么目标下、按什么步骤、做到什么算成功」的一小段程序。

最初的写法很随意：一个正文里什么都有——提示词、步骤、注意事项、例子。这让夜间自动改进失效。模型拿到失败日志后只能整篇重写，因为它不知道哪一行对应哪一步；它也无法判断改动是否更好，因为没人说得清"这次成功"是哪一步带来的；技能还会静默过期，因为文件里没写它引用的工具和版本。

我们给技能定了一套格式：技能必须声明自己属于哪一类（拆目标 / 执行动作），必须写清适用目标与状态前提，每一步要有编号、要调用的动作、参数和**能观测到的期望**，要有终态校验与失败降级，还要带**来源锚**（来自哪天的哪条日志）和版本谱系。

有了这个格式，改进才能自动化：夜里我们从日志里找失败模式，只允许六类局部改动，然后把改后的技能在**改动发生之前的历史日志**上回放——动作更少、失败更少才采纳。在 N 天、M 条目标上，改动采纳率从 x% 提到 y%，平均动作数下降 z%。

**关键词**：长期运行智能体；技能格式；自改进；日志回放；目标树

### English

**Abstract**

We build an agent that runs around the clock: an ESP32 as the body (hearing, speaking, seeing, moving, expressing) and a small computer as the brain. It has exactly two operations — decompose the current goal into finer subgoals, or execute one real action. What it learns is stored as markdown "skills": small programs that say, for a given kind of goal, which steps to take and what counts as success.

Our first version failed at night. Everything — prompt, steps, pitfalls, examples — was dumped into one body of text. When the model tried to improve a skill from the day's logs, it could only rewrite the whole thing: it did not know which line corresponded to which step, could not tell whether an edit helped, and could not notice when a skill silently went stale because nothing recorded which tools and versions it depended on.

We therefore define a format: every skill declares its kind (goal decomposition or action plan), its applicable goals and state preconditions, numbered steps with the action to call, its arguments and an **observable expectation**, a final check with a fallback, and **provenance** (which log entry it came from) plus version lineage.

With this format, improvement can be automated. Overnight we mine failures from logs, allow only six kinds of local edit, and replay the edited skill on logs recorded **before** the edit: fewer actions and fewer failures are required for acceptance. Over N days and M goals, the acceptance rate rises from x% to y% and mean actions per goal drop by z%.

**Keywords**: long-running agents; skill format; self-improvement; log replay; goal trees

---

## 2. 学术版摘要（投稿用；压紧，但保留那个例子）

### 中文

**摘要**

长期运行的个人级智能体与一次性任务型智能体有一个实际差别：它必须在两次运行之间沉淀经验，否则每天从零开始。我们在一台 24 小时运行、每日快照的智能体上研究这件事。它的动作空间只有两个原语——**目标分解**与**原子动作执行**，因此技能被约束成目标树上的可执行节点。例如目标「把飞书里最新一条客户消息念出来」，对应技能是三步：

```
when: 目标属"转达/念出来/播报"，且喇叭可用、非静音
s1  feishu.fetch_messages {limit:3}      expect: 至少 1 条且有文本
s2  esp32.speak {text: $s1.latest.text}  expect: 播报成功
校验: s2 成功；失败则降级为桌面通知
```

以自由文本存放这类技能会带来三个具体故障：**改不动**（一处失败导致整篇重写）、**判不了**（成功无法归因到某一步）、**追不回**（技能引用的工具与版本变化后静默过期）。我们提出一套技能格式来消除它们：技能须声明类型（目标分解 / 动作计划）；按**目标签名**而非内容相似被检索，且允许返回"无合适技能"；每一步具有稳定标识、动作、参数与可观测期望；技能携带终态校验、失败降级、来源锚（日志引用）与版本谱系，预算有界。

在此基础上给出一个不依赖基准的验收方法：系统日志只追加、每日快照，因此**改动前的历史日志可直接作为留出集**；候选改动须在回放上严格优于现版本才被接受，且只允许六类局部编辑。在 N 天、M 条目标上，采纳率由 x% 升至 y%，平均动作数下降 z%，并给出改进率的逐日曲线。结论是：对持续运行的智能体，技能格式的精细程度不是风格偏好，而是**自我改进能否落地的前置条件**——步可寻址才能局部改，期望可观才能归因，来源可追才能区分"技能过期"与"模型变差"。

**关键词**：长期运行智能体；技能格式；技能库维护；自改进；日志回放

### English

**Abstract**

A long-running personal agent differs from an episodic one in a practical respect: it must accumulate experience between runs, or it restarts from zero every day. We study this on an agent that runs continuously, snapshots its state daily, and whose action space has only two primitives — **goal decomposition** and **atomic action execution**. Its skills are therefore constrained to be executable nodes of a goal tree. For the goal "read out the latest customer message from Feishu", the skill is:

```
when: goal in {relay, read out, announce}, speaker available, not muted
s1  feishu.fetch_messages {limit:3}      expect: >=1 message with text
s2  esp32.speak {text: $s1.latest.text}  expect: spoken == true
check: s2 succeeded; on failure, fall back to a desktop notification
```

Storing such skills as free-form text causes three concrete failures: they cannot be **edited locally** (one failure leads to a wholesale rewrite), cannot be **diagnosed** (success is not attributable to a step), and cannot be **tracked** (a skill silently goes stale once the tools or versions it references change). We present a skill format that removes these failure modes: a skill declares its kind (goal decomposition or action plan); it is retrieved by a **goal signature** rather than content similarity, and may return "no applicable skill"; each step carries a stable identifier, an action, arguments, and an observable expectation; each skill carries a final check, failure fallbacks, provenance (a log reference), version lineage, and a bounded budget.

We then give a benchmark-free acceptance method. Because logs are append-only and snapshots are daily, **logs recorded before an edit serve as the held-out set**: an edit is accepted only if replay strictly improves on them, and only six kinds of local edits are permitted. Over N days and M goals, the acceptance rate rises from x% to y%, mean actions per goal drop by z%, and we report a per-day curve of improvement rate. Our conclusion: for continuously running agents, the granularity of the skill format is not a matter of taste but a **precondition for self-improvement** — addressable steps enable local edits, observable expectations enable attribution, and provenance separates a stale skill from a degraded model.

**Keywords**: long-running agents; skill format; skill-library maintenance; self-improvement; log replay

---

## 3. 标题候选

### 直白型（第一眼就知道在做什么）——现在更推荐

- **中文**：技能的写法决定它能不能自我改进：一个 24 小时智能体的技能格式与日志回放验收
- **英文**：How a Skill Is Written Decides Whether It Can Improve: A Skill Format and Log-Replay Validation for an Always-On Agent

### 现象型（三个否定，读者立刻知道你在解决什么）

- **中文**：改不动、判不了、追不回：长期运行智能体的技能格式
- **英文**：Uneditable, Undiagnosable, Untrackable: A Skill Format for Long-Running Agents

### 学术 claim 型（最保守，投稿评审用）

- **中文**：技能格式的粒度约束自我改进的粒度：面向长期运行智能体的目标绑定技能格式
- **英文**：Format Granularity Constrains Improvement Granularity: A Goal-Bound Skill Format for Long-Running Agents

### 其余备选

| 中文 | 英文 | 用在 |
|---|---|---|
| 只会"定目标"和"发动作"的智能体，需要什么样的技能？ | Skills for an Agent That Only Sets Goals and Acts | workshop |
| 日志即留出集：用历史回放验证技能的持续改进 | The Log Is the Held-Out Set: Validating Skill Improvement by Replay | 方法为主 |
| 先定格式，再谈进化 | Format Before Evolution | position paper |

**建议**：想让人一眼看懂 → **直白型**标题 + 第 1 节直白版摘要；投稿评审 → **现象型**标题 + 第 2 节学术版摘要。

---

## 4. 定稿前要填的空

1. **N 天、M 条目标**：实际跑出来的天数与目标条数。
2. **x% → y%**：改动采纳率（旧三段式人工改 vs 新格式自动改）。
3. **z%**：平均动作数下降幅度。
4. **边际收益曲线**：不衰减 / 衰减——决定结论能说"证据"还是只能说"给出了可测量的口径"。
5. **对照怎么设**：同一批历史 goal，旧格式与新格式各回放一遍。没有这个对照，学术版摘要不成立。

---

## 5. 三个坑（前一版讲过的，仍然成立）

| 不要写 | 改成 |
|---|---|
| "首次提出 skill 协议" | 已有至少六份格式提案；写成"把格式重新表述为对改进能力的约束" |
| "证明了递归自我改进可行" | 只有边际收益不衰减才可说"提供早期证据"；否则写"给出可测量的观测口径" |
| "在所有任务上优于基线" | 单系统单用户无基准；写成"在 N 天真实运行上"，并写清统计口径 |
