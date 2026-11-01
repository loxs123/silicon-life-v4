# 硅基生命的 Skill 协议（草案 v0.1）

> 目标：给这个项目定一套 **只服务两个操作** 的 skill 格式，并且让"自进化"成为格式的内建能力，而不是事后补的补丁。
> 相关调研见 [`docs/rsi/04-skill-protocol.md`](rsi/04-skill-protocol.md)（协议层横向对比）与 [`docs/rsi/03-skills.md`](rsi/03-skills.md)（自进化方法逐篇）。

---

## 0. 三个硬约束

这套协议只允许两件事：

1. **确定目标** —— 把高层目标拆成子目标（或把子目标落到某个技能上）；
2. **执行基本动作** —— 调用一个真实存在的原子动作，改变世界状态。

所以：**技能的输出只能是"子目标"或"原子动作"，不能是"一段建议"。** 任何一段不能让机器直接执行的文字，都是协议违规。

第三个约束来自你的要求：**技能必须为目标服务，并且是通过目标被检索出来的执行工具。** 于是检索键必须是"目标"，不是"技能内容"。

---

## 1. 现状与它的问题

今天的格式（`core/hooks/skills/readme.md` + `tools/skill_loader.py`）：

```markdown
## name
plan

## match_function
```python
def match(goal):
    return goal == '今天还没有计划'
```

## content
今天是 {date}。……只输出一个 JSON，里面有两个键：target_list、cur_target。
```

加载器做的事很直接：正则切三段 → `exec` 那段 Python 拿到 `match` → `content` 原样取出来当提示词。

它已经抓住了三个正确的点：**技能按目标匹配**、**技能可被生成**、**技能是文件（可 diff、可快照）**。但有四处会在自进化时立刻卡住：

| 问题 | 后果 |
|---|---|
| `content` 是自由文本 | 无法判断它是"拆目标"还是"发动作"；无法逐节点修改，只能整篇重写 |
| `match` 是**精确字符串比较**的代码 | 换一种说法就不命中；且 `exec` 任意代码，安全和可审计都成问题 |
| 没有校验/失败模式字段 | 执行完无法判断"这一步是否成功"，进化就没有信号 |
| 没有版本、来源、身份 | 改完之后无法归因"是哪次改动导致的"，回滚只能靠整目录快照 |

调研里的结论正好一一对应：**SkillBoost 能做组件级归因，是因为它把技能拆成了带槽位的结构；AIP 能把失败追到脚本级，是因为每个节点有 ID 且可寻址；Repo2Skill-Evo 里技能静默过期，是因为没有"来源锚"字段。**

---

## 2. 自进化需要什么：把"进化"拆成 5 个动作

协议里每个字段，都必须服务下面五件事之一；不服务就不要加。

| # | 进化动作 | 需要协议提供什么 |
|---|---|---|
| E1 | **看到**（哪一步错了） | 每步有稳定 ID 与可观测结果；失败模式有名字 |
| E2 | **改**（局部而不是重写） | 节点可寻址；改动粒度到单步/单字段 |
| E3 | **验**（改完真的更好吗） | 每步有 check；有可回放的成功判据 |
| E4 | **回滚 / 归因** | version + parent + change_reason + 来源锚 |
| E5 | **淘汰**（该不该留） | 贡献可分（技能级、步级）；库有身份与生命周期 |

这五条就是下面字段表的验收标准。

---

## 3. 由"两个操作"直接推出两类技能

这是整套协议的根。既然只有两个操作，技能就只有两种 **kind**：

| kind | 输出 | 谁消费 | 例子 |
|---|---|---|---|
| `goal_decompose` | **一组子目标**（带时间/顺序/依赖） | 目标树挂新节点 | `plan`：把"今天还没有计划"拆成 07:00–23:00 的时间块 |
| `action_plan` | **一串原子动作**（带参数与期望） | 执行器逐步执行 | `read_aloud_message`：取飞书最新消息 → 用 ESP32 念出来 |

判定规则写死在协议里（也是 SKILL CREATOR 的准入检查）：

- 如果目标**不需要再拆**、且当前有工具能直接做 → 用它自己的 `action_plan`；
- 如果目标**还能拆**、且拆完每块都更具体 → 挂一个 `goal_decompose`；
- 两者都不成立 → **没有合适技能**，这时正确的行为是"承认做不了"，而不是编一个技能。这条要写进 `GOAL ADJUSTOR`。

叶子节点 = 原子动作，非叶子 = 目标，这个和 `core/readme.md` 里的目标树定义一致；协议只是让"叶子"可机器识别。

---

## 4. 目标协议：技能服务于目标，目标也必须能被机器判断

技能是"通过目标检索出来的执行工具"，那么**目标本身必须结构化**，否则检索键是模糊的、完成判据也是模糊的。

```yaml
# goal record（目标树节点，落在 states/ 里，不是在 skill 文件里）
id: g-20261024-0715
parent: g-20261024-07
statement: 把飞书里最新那条客户消息念给我听
kind: leaf | node                      # leaf 表示可直接执行
done_when:                             # ★ 必须可判定，且尽量可观测
  - action_effect: esp32.speak.spoken == true
  - world: 消息内容已包含在播报文本里
budget:
  deadline: "07:20"
  max_actions: 6
status: pending | active | done | failed | dropped
origin: skill:read_aloud_message@3     # 由哪个技能生成的子目标（可归因）
```

四个字段是关键：

- **`done_when` 必须可判定**。写成"用户满意"就不是协议的一部分——那是人的判断，不能进 `GOAL CHECKER`。
- **`max_actions`／`deadline` 是预算**，用来防"一个目标把一整天耗光"，也是进化时判断"这次改动是否更省"的对照。
- **`origin`** 让"这个子目标是哪个技能生成的"可追溯——出问题能直接定位到技能版本。
- **`status` 是状态机**，`failed` 与 `dropped` 要分开：前者是执行失败（回灌给进化），后者是目标本身被放弃（回灌给 GOAL ADJUSTOR）。

---

## 5. 技能协议：一份技能 = 目标签名 + 计划体 + 校验

### 5.1 Frontmatter（机器读的部分）

```yaml
---
name: read_aloud_message                # 与文件名一致，snake_case
kind: action_plan                       # action_plan | goal_decompose
version: 3                              # 单调递增，回滚的锚
parent: read_aloud_message@2            # 谱系：从哪个版本改来
change_reason: "加上喇叭未就绪的回退，见 log 2026-10-23"   # ★ 进化时必填
source:                                 # ★ 来源锚：治"静默过期"
  - log: hooks/logs/2026-10-22.log#L118-L124
  - experience: memory/experience.md#2026-10-20
when:                                   # ★ 检索键：按目标匹配，不是按内容相似
  goal_kinds: [转达消息, 念出来, 播报]
  require_state: [mqtt_online, speaker_ok]
  exclude_state: [quiet_mode]           # 静音时不该用这条
  examples: ["把飞书那条消息念给我听", "读一下客户刚发的话"]
budget:
  max_actions: 6
  timeout_s: 30
---
```

**为什么是 `when` 而不是可执行 `match` 代码**：现在的 `match(goal)` 是精确字符串比较，等于要求用户永远用同一句话；而我们要的是"按目标检索"。改成**结构化签名 + 排序打分**（见 §7），既能泛化，又能被非程序员审阅、diff、局部修改。

### 5.2 正文（人读 + 执行器读的部分）

正文只有三段，顺序固定：

**① `## 步骤`** —— 两种形态，二选一，且必须在 `kind` 里对上：

- `action_plan`：**动作表**，每行一个动作，字段固定：

```yaml
- id: s1
  do: feishu.fetch_messages          # 必须来自工具注册表，不能自造
  args: {limit: 3, unread_only: true}
  expect: {count: ">=1", has_text: true}     # ★ 可观测的期望；没有就写 none
- id: s2
  do: esp32.speak
  args: {text: "${s1.latest.text}", rate: 1.0}
  expect: {spoken: true}
```

- `goal_decompose`：**子目标表**（形态同 `plan` 现在产出的 JSON）：

```yaml
- id: g1
  statement: "07:00-09:00 处理飞书上的待办"
  done_when: [行动项均已回复或标记]
  order: 1
```

**② `## 校验`** —— 至少一条终态判据：

```yaml
final: s2.expect.spoken == true
on_fail:
  - if: "s2 failed with speaker_not_ready"
    then: 改用 desktop.notify（降级，不重试同类动作）
```

**③ `## 备注`** —— 已知坑、边界条件、观察来源。这一段是整个协议里**唯一允许自由文本**的地方，因为它不参与执行判定。`failure_modes` 建议在这里用固定列表写，方便进化时按名字归因。

### 5.3 字段 → 自进化能力对照

| 字段 | 服务哪个进化动作 | 依据 |
|---|---|---|
| `id`（每步） | E1 看到、E2 局部改 | AIP：可按节点寻址，失败能追到脚本级 |
| `expect`／`## 校验` | E1、E3 | SkillBoost：`V`（验证器）与 `F`（失败模式）是组件级归因的前提 |
| `failure_modes`（备注内固定列表） | E1、E5 | SkillBoost 的 `F` 槽位 |
| `version` / `parent` / `change_reason` | E4 回滚与归因 | Skillware：Lifecycle Continuity |
| `source`（log / experience 引用） | E4、E5 | Repo2Skill-Evo：无来源锚 → 静默过期（中位数 92 行） |
| `when.require_state` / `exclude_state` | E3、E5 | Library Drift：**能拒绝注入**本身就是防漂移机制（A2 只有 +0.077） |
| `budget` | E3、E5 | SpecRSI／SEA-Eval：不把成本放进分母，增益无法比较 |
| `kind` | 全流程 | 只有两个操作，必须先分清是哪一种 |

---

## 6. 两个完整示例（用项目真实能力）

### 6.1 `action_plan`

```markdown
---
name: read_aloud_message
kind: action_plan
version: 1
parent: null
change_reason: "首次创建，来源见 source"
source:
  - log: hooks/logs/2026-10-22.log#L118-L124
when:
  goal_kinds: [转达消息, 念出来, 播报]
  require_state: [mqtt_online, speaker_ok]
  exclude_state: [quiet_mode]
  examples: ["把飞书那条消息念给我听"]
budget: {max_actions: 4, timeout_s: 30}
---

## 步骤
- id: s1
  do: feishu.fetch_messages
  args: {limit: 3, unread_only: true}
  expect: {count: ">=1", has_text: true}
- id: s2
  do: esp32.speak
  args: {text: "${s1.latest.text}", rate: 1.0}
  expect: {spoken: true}

## 校验
final: s2.expect.spoken == true
on_fail:
  - if: "s1.count == 0"
    then: 直接回复"没有未读消息"，不调用喇叭
  - if: "s2 failed with speaker_not_ready"
    then: 降级到 desktop.notify，不重试同类动作

## 备注
- 失败模式：speaker_not_ready（喇叭被占用）／msg_too_long（超过单次播报上限，需分段）
- 播报前不要读出消息里的链接和附件名
```

### 6.2 `goal_decompose`（改造现有 `plan` 的最小版本）

```markdown
---
name: plan
kind: goal_decompose
version: 2
parent: plan@1
change_reason: "把自由文本改为可解析的子目标表，加上 done_when"
source:
  - log: hooks/logs/2026-10-20.log#L44-L51
when:
  goal_kinds: [今天还没有计划, 安排今天]
  require_state: [has_calendar]
budget: {max_actions: 0, timeout_s: 60}
---
## 步骤
（本技能的步骤由模型生成，但必须符合下面的输出结构）

## 输出结构
- id: g<n>
  statement: "HH:MM-HH:MM <具体目标>"
  done_when: [<可判定条件>]
  order: <按时间递增>
## 校验
final: 时间块连续覆盖 07:00–23:00，无空隙、无重叠
on_fail:
  - if: "有空隙"
    then: 补齐空隙后再提交，不要提交半成品
## 备注
- 计划里不要出现吃饭、午休、洗漱这类生理条目
- 只排现有能力真能做的事（键鼠、截屏、剪贴板、飞书、文件/记忆/技能读写）
- 总结与分析留给 dream，不要排进白天计划
```

注意 6.2 里出现了第三种形态：**正文是"输出结构 + 校验"，计划本身由模型生成**。这在协议里要显式允许，但必须满足两条——**声明输出结构** + **有可判定的校验**。否则它就退化成"一段建议"。

---

## 7. 检索：从"第一个命中"改成"按目标排序"

技能是"通过目标检索出来的工具"，所以检索是一个**排序**问题，不是一个**布尔**问题。

```
score(skill, goal) =
    0.5 * 目标签名匹配(goal_kinds ∩ goal.kind_terms)
  + 0.2 * 状态前置条件满足(require_state / exclude_state)
  + 0.2 * 历史效用(该技能在该类目标上的成功率 EMA)
  + 0.1 * 成本惩罚(历史平均动作数 / 墙钟)
```

四条设计理由，每条都有调研依据：

- **签名匹配而不是字符串相等**：现在的 `goal == '今天还没有计划'` 只对一句话生效。
- **`exclude_state` 必须是一等公民**：Library Drift 的 A2 显示，绕开"能不能说不用"这个门、只注入搜出来的第一个技能，收益只有完整配方的 **24%**（+0.077 vs +0.328）——**"能拒绝"本身就是能力**。
- **效用必须进排序**：Selm 的做法是 `(1−w_u)·相关性 + w_u·历史效用`；纯相关性会长期选到"像但不好用"的技能。
- **成本要进排序**：否则进化会朝"堆更多动作"的方向漂（SEA-Eval 的教训：成功率相同，token 消耗可差 31.2 倍）。

如果所有技能得分都低于阈值 → **返回"没有合适技能"**，交给 GOAL ADJUSTOR。这条不许省。

---

## 8. SKILL CREATOR 的准入检查（7 条硬规则）

新技能或改动后的技能，进库前必须全过；任一不过就打回，并记日志。

1. **`kind` 合法**，且正文形态与 `kind` 一致（`action_plan` 必须有动作表，`goal_decompose` 必须有子目标表或输出结构）。
2. **每个 `do` 都在工具注册表里**（不许出现 `do: 让用户自己去弄`）。
3. **每个动作有 `expect`，或显式写 `expect: none`**——显式写 none 是允许的，但要在备注里说明为什么没法校验。
4. **`## 校验` 至少一条终态判据**，且引用的变量在步骤里存在（不许写 `final: 一切正常`）。
5. **`budget` 有界**（`max_actions` ≤ 全局上限；`timeout_s` 有值）。
6. **`source` 非空**——新技能必须能指向"哪段经历/日志让它存在"。这条是防技能静默过期和防幻觉的第一道闸。
7. **`change_reason` 非空**（v1 写"首次创建"）。没有理由的改动一律不接收。

配套一条**软检查**（不阻断，但记分）：`when.examples` 至少 2 条，且互不重复——测试检索泛化用。

---

## 9. 自进化闭环：用日志当 holdout

这套系统有个天然优势：**"模型可见 = 已落日志"**，而日志只追加。这意味着**历史日志可以直接当回放集**，不需要额外造数据。

每天夜里（dream 的 `optimize_skill`）跑：

1. **收集**：从当天日志里抽出每个技能的调用记录——`(goal, skill@version, 动作序列, 每步 expect 的实际值, 终态校验结果, 动作数, 墙钟)`。
2. **归因**（E1）：按 `failure_modes` 的名字聚类失败；找出**总是同一个 `id` 步失败**的模式（AIP 的做法：能追到脚本级，就能精确修）。
3. **提改动**（E2）：只允许六种改动，其他一律不改——
   | 改动 | 触发信号 |
   |---|---|
   | 改 `expect`（更严或更松） | 该步 expect 与实际反复不一致 |
   | 加/删/换一个动作 | 某步反复失败且换动作能过 |
   | 改 `when`（放宽/收紧/加 exclude） | 命中错目标，或该命中却没命中 |
   | 改 `budget` | 超预算被截断 |
   | 拆技能（目标太宽） | 一个技能服务多个 goal_kind 且成功率方差大 |
   | 合并技能（重复） | 两个技能 `when` 高度重叠且动作表相似 |
4. **回放验证**（E3）：把改动后的技能在**最近 N 天的历史日志**上重放——给定同样的 goal，新技能是否动作更少、失败更少、终态校验通过率更高。**只有在这批历史 goal 上严格变好才接受**（严格大于；平局即拒绝）。
5. **落地**（E4）：写回文件，`version + 1`，`parent` 指向旧版本，`change_reason` 写清"哪条日志、哪个失败、改了什么"。
6. **退役**（E5）：连续 K 天没被命中、或使用后成功率低于阈值 → 移入 `skills/retired/`（**不删**，并阻止同名重建，避免删了又长回来的振荡）。

**为什么用"回放"而不是"当天表现"**：当天数据太少，噪声大；而且拿"被改动的这一天"去评估这次改动，等于用训练集当测试集。日志回放能给出一个便宜、可复现、口径固定的对照——这正是调研里各条工作都缺的东西（SpecRSI 要单独设计"验证预算"，我们这里日志天然免费）。

**一个约束要写死**：回放必须用**改动之前的日志**，且回放集与"驱动这次改动的日志"不能是同一批（否则就是自证）。

---

## 10. 迁移路径（不破坏现有代码）

现在是三段式、`exec` Python 谓词。建议分三步，每一步都可独立上线：

| 步 | 做法 | 兼容性 |
|---|---|---|
| **1. 加字段，不改解析** | 在 frontmatter 里加 `kind/version/when/budget/source/change_reason`；`skill_loader` 仍读 `## content` 作为提示词 | 老技能零改动即可跑（缺字段按默认值） |
| **2. 双读（`match` 与 `when` 并存）** | 若 frontmatter 有 `when` → 用签名匹配打分；否则回退到 `match(goal)` 布尔判定 | 老技能继续用旧路径 |
| **3. 结构体上线** | `action_plan` 用动作表；`goal_decompose` 用子目标表；`match` 代码字段废弃（只保留生成能力，不再 `exec`） | 需要执行器支持 `expect` 与 `${s1.xxx}` 变量引用 |

第 3 步的收益是顺带修掉两个隐患：`exec` 任意 Python（安全 + 不可审）、以及"精确字符串比较"导致的检索脆弱。

---

## 11. 反模式（明确不要做）

1. **不要给正文加"摘要/背景/示例"这类自由段落**。SkillReducer 的实证：公开技能 **26.4% 没有描述、>60% 正文不可执行**；AIP 的结论也一样——自由散文让 agent 每次重新推导。正文只保留步骤/校验/备注。
2. **不要把状态写回技能文件**（成功率、上次使用时间）。技能要保持"可 diff 的代码"，统计放 `states/`。否则每次执行都会脏化文件，版本号失去意义。
3. **不要用一个技能服务多个目标**。宁可拆两个、让 `when` 各自收紧——Library Drift 的教训是库宽无上限 + 无淘汰会让检索整体退化。
4. **不要让模型直接改 `when` 里的 `require_state`** 来自救失败。状态前置条件被放宽，等于让技能在不适用的场景里被调用，短期涨分、长期崩盘（这正是 SkillBoost 要设"回归上限"的原因）。
5. **不要在 `## 备注` 里藏第二个计划**。备注只能写坑与边界；再出现步骤就是协议违规（进化时会误改）。
6. **不要为了"看起来更强"把 `expect` 放宽**。放宽 `expect` 会让"通过"失去信息量——Ratchet 的结论是：judge 把失败判成通过的比例一旦超过 `(1−τ)/2`，**任何样本量都退不掉坏技能**。

---

## 12. 未决问题（需要你拍板的）

1. **原子动作的词汇表由谁定？** 建议由工具注册表自动生成（`hooks/tools/` + ESP32 主题 + 三个工具口），技能里只能引用名字。要不要允许"参数化动作名"？
2. **`goal_decompose` 的输出要不要给例子**？给了会提升稳定性，但会诱导模型抄结构、降低泛化。
3. **回放的窗口 N 取多少？** 3 天太短、30 天太贵。建议先用 7 天，且只回放"该技能被命中过"的那些 goal。
4. **退役阈值 K 取多少**？Library Drift 的反例是"证据不足就退役 → −0.019"，所以宁慢勿快，建议 K ≥ 14 天。
5. **要不要给技能加 `owner`**（自己写的 / 用户教的 / 从别处 import 的）？在只有一个人的系统里可能多余，但会决定"谁的改动优先"。

---

## 附：字段速查

| 字段 | 必填 | 取值 | 一句话理由 |
|---|---|---|---|
| `name` | ✅ | snake_case，与文件名一致 | 身份 |
| `kind` | ✅ | `action_plan` / `goal_decompose` | 只有两个操作，先分清 |
| `version` | ✅ | 整数，单调递增 | 回滚与归因的锚 |
| `parent` | ✅ | `name@version` 或 `null` | 谱系 |
| `change_reason` | ✅ | 一句话 + 日志引用 | 没有理由的改动不接收 |
| `source` | ✅ | log / experience 引用列表 | 治静默过期 |
| `when.goal_kinds` | ✅ | 词表 | 检索主键 |
| `when.require_state` | ✗ | 状态名列表 | 防误用 |
| `when.exclude_state` | ✗ | 状态名列表 | **"能拒绝"是能力** |
| `when.examples` | ✗ | ≥2 条 | 测泛化 |
| `budget.max_actions` | ✅ | 整数 | 防一个目标耗光一天 |
| `budget.timeout_s` | ✅ | 整数 | 同上 |
| `步骤[].id` | ✅ | `s1,s2…` 或 `g1,g2…` | 可寻址 |
| `步骤[].do` | ✅ | 工具注册表内的名字 | 可执行、可检查 |
| `步骤[].args` | ✗ | 支持 `${s1.latest.text}` | 上下文传递 |
| `步骤[].expect` | ✅ | 可观测断言 或 `none` | 进化的信号源 |
| `## 校验`.final | ✅ | 可判定表达式 | 终态判据 |
| `## 校验`.on_fail | ✗ | 降级/跳过策略 | 防同类重试死循环 |
| `## 备注` | ✗ | 自由文本（含失败模式命名） | 唯一允许散文的地方 |
