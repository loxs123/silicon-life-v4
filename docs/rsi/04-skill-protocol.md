# Skill 协议层调研：先把格式定下来，再谈自进化

> 2026-10 ｜ 回答一个问题：**是否存在一类专门"定义 skill 格式"的工作？**
> 结论：**有，但只协议到外壳——`name` / `description` / frontmatter 是定死的，正文（body）仍然是自由 Markdown，没有任何结构约束。** 你的直觉不光对，而且 2026 年已经有好几篇论文专门在补这一层。

---

## 0. 六个结论

1. **正式标准存在，但只管外壳。** Agent Skills 规范（[agentskills.io/specification](https://agentskills.io/specification)）把 frontmatter 六个字段、目录结构、渐进披露、validation 都定死了，**唯独没有规定正文怎么写**。
2. **"正文自由"被点名成了性能问题。** Skill-as-Pseudocode 的原话是：markdown 技能以自由散文交付，**迫使 agent 在每次检索后重新推导输入 schema 和调用语法**，于是形成"困惑 → 重新检索 → 还是困惑"的循环。AIP 开头几乎同一句："skills today consist largely of free-form prose"。
3. **补正文协议有四条路**：类型化契约（SkillOps 的 `P,O,A,V,F`）、类型化伪代码（SaP）、可执行图 + YAML schema（AIP）、软件本体论 + 生命周期身份（Skillware）。SoK 则给出"协议**应该**包含什么"的清单。
4. **有硬收益，不是洁癖。** SaP：配对胜 82:47（`p=8.2e-5`）、输入 token −22.8%、LLM 调用 −14.5%。AIP：把人类技能编译成图后，Sonnet 的平均任务奖励 **0.60 → 0.71**、通过率 **53% → 67%**（Wilcoxon `p=0.011`）。
5. **这层是自进化的前置条件。** AIP 的论证最直接：因为每个技能 **schema 可校验、可功能测试、可按节点寻址**，两例失败被定位到**脚本级**，改 spec 重编译后零回归恢复（其中一例 0/5 → 5/5）。没有协议时，改进只能整体重写。
6. **但缺一块没人做**：目前没有工作把"正文协议"和"自进化的门控"接起来——即**协议级约束如何进入接受/淘汰判据**。这是空白。

---

## 1. 协议分五层，成熟度递减

| 层 | 定义什么 | 谁在做 | 成熟度 |
|---|---|---|---|
| **L0 外壳** | 目录 + `SKILL.md` 必须存在 | Agent Skills 规范 | ✅ 正式标准 |
| **L1 元数据** | `name` / `description` / `license` / `compatibility` / `metadata` / `allowed-tools` | Agent Skills 规范 | ✅ 正式标准（含长度与字符集约束） |
| **L2 正文结构** | body 怎么分块、哪些常驻、哪些按需加载 | SkillReducer（core vs on-demand）、SbP/SaP（伪代码）、AIP（节点图） | 🟡 论文提案 |
| **L3 类型与契约** | 前置条件 / 操作 / 产物类型 / 验证器 / 失败模式 | SkillOps `(P,O,A,V,F)`、SaP typed contract | 🟡 论文提案 |
| **L4 身份与生命周期** | 同一身份的更新、维护、回滚、退役 | Skillware（Lifecycle Continuity） | 🟡 概念框架 |
| **L5 治理与认证** | 可信、可验证、可认证 | SoK 的结论与安全分析 | 🔴 早期 |

一句话：**L0/L1 已经有工业标准，L2–L5 全是论文，而且互不统一。**

---

## 2. 逐篇拆解（同样用三问）

### P1. Agent Skills 官方规范：定了外壳，没定正文

*开放标准（[agentskills.io](https://agentskills.io/specification)），2025 年由 Anthropic 提出并开放，非论文*

**① 定了什么**

- **目录**：必须有一个 `SKILL.md`；可选 `scripts/`（可执行代码）、`references/`（文档）、`assets/`（模板与资源）。
- **Frontmatter 六个字段**（含硬约束）：

| 字段 | 必填 | 约束 |
|---|---|---|
| `name` | ✅ | ≤64 字符，仅小写字母/数字/连字符，首尾不能是连字符 |
| `description` | ✅ | ≤1024 字符，非空，须说明"做什么 + 何时用" |
| `license` | ✗ | 许可证名或指向随包文件 |
| `compatibility` | ✗ | ≤500 字符，环境要求（目标产品、系统包、网络访问） |
| `metadata` | ✗ | 任意 string→string 映射 |
| `allowed-tools` | ✗ | 空格分隔的预授权工具（**实验性**） |

- **另有三个机制**：渐进式披露（元数据常驻 → 正文按需读 → 附加文件再按需）、文件引用规则、**validation**。

**② 怎么定 / 效果**
规范以"客户端实现"为单位落地（Claude.ai、Claude Code、Agent SDK 等），并提供校验章节；官方还给"优化 description""评估技能"的实践指南。

**③ 场景**
所有兼容客户端。**关键缺口**：正文是自由 Markdown——六个字段只管"能不能被找到"，不管"里面写的对不对"。

---

### P2. SoK: Agentic Skills：协议"应该"有什么

*Jiang et al.，2026-02，[arXiv:2602.20867](https://arxiv.org/abs/2602.20867)，安全视角（cs.CR）*

**① 它定义的 skill 是什么（这基本就是一份字段清单）**
> callable modules that package procedural knowledge with **explicit applicability conditions, execution policies, termination criteria, and reusable interfaces**.

也就是：可调用模块 = 过程性知识 + **适用条件** + **执行策略** + **终止条件** + **可复用接口**。这四样正是当前正文里"随手写、没有槽位"的东西。

**② 怎么梳理 / 主要结论**
- 沿完整生命周期（发现、练习、蒸馏、存储、组合、评估、更新）划分；
- 给出**七种设计模式**（元数据驱动的渐进披露、可执行代码技能、自进化技能库、市场分发等）；
- 再给一组正交的 **representation × scope** 分类（自然语言/代码/策略/混合 × web/OS/软件工程/机器人）；
- 安全分析：供应链风险、**通过技能载荷做 prompt injection**、分级可信执行。案例是 **ClawHavoc**——约 **1,200 个恶意技能**渗透进一个主流 agent 市场，规模化外泄 API key、加密钱包、浏览器凭据。

**③ 场景与去向**
结论直指"robust, **verifiable**, and **certifiable** skills"——即 L5。它是目前唯一从安全侧论证"必须有协议"的工作。

---

### P3. Skillware：把技能当"独立软件对象"，补身份层

*Fan & Lan，2026-07，[arXiv:2607.18970](https://arxiv.org/abs/2607.18970)，cs.SE*

**① 优化什么（其实是在定义本体）**
把技能重述为 **Behavioral Artifact**，并给出三层区分：

- **Skill Artifact**：规定可复用的任务行为（就是那份文档）；
- **Skillware Unit**：以**独立身份 + 生命周期**来管理这个 artifact（软件意义上的"单元"）；
- **Agent Host**：运行时解释该单元的宿主。

三个**必要条件**界定类别成员：**行为优先性**、**独立软件身份**、**与 Agent Host 的执行关系**。另提一个独立属性 **Lifecycle Continuity**——同一个单元身份能否在**更新、维护、回滚、移除**之后延续。

**② 怎么论证**
用四类证据：Agent Skills 规范本身、一个**冻结语料（138,133 条去重 SKILL.md，关联 20,556 个仓库标识）**、15 个类别边界案例、13 个固定版本的工程实现。

**③ 为什么这对自进化重要**
自进化最怕"改完之后无法判断是不是同一个东西"。**身份 + 生命周期连续性**是回滚、归因、审计的前提；没有它，技能库只能靠文件名和内容哈希凑合（Library Drift 那边的 `body-hash collisions` 就是这种凑合）。

---

### P4. SkillOps：给正文加"类型化契约槽位"

*Pu, Song, Zhao，2026-05，[arXiv:2605.13716](https://arxiv.org/abs/2605.13716)，cs.SE，投 NeurIPS 2026*

**① 优化什么——这是最接近你说的"正文协议"的提案**
每个技能不再是一段话，而是一个**类型化契约** `s = (P, O, A, V, F)`：

| 槽位 | 含义 | 解决什么 |
|---|---|---|
| **P** Precondition | 调用该技能的前置条件 | 什么时候能用（可机器检查） |
| **O** Operation | 可执行的操作本体 | "做什么"与描述分离 |
| **A** Artifact | 产出物的**类型** | 能不能接给下一个技能 |
| **V** Validator | 对 A 的验证器（`V=∅` 即"验证缺口"） | 局部正确性检查 |
| **F** Failure modes | 已知失败模式 | 失败归因的锚点 |

**② 怎么优化**
把契约组织成 **HSEG（分层技能生态图）**：内部是每个技能的契约图，外部用**四种带类型的有向边**连技能——`dep`（产物满足下游前置）、`comp`（产物类型兼容下游输入）、`red`（接口等价 = 冗余）、`alt`（同目标不同实现）。然后在两个循环里用：
- **任务时**：匹配 → 依赖拼接（只有 `dep` **且** `comp` 才允许转移）→ 插入 validator/adapter（adapter 只在类型可修复时才插）→ 局部修复；
- **库维护时**：五维健康诊断（utility / redundancy / compatibility / failure-risk / validation-gap），执行 `merge / repair / retire / add_validator / add_adapter / instantiate`。

**③ 前后对比 / 场景**
ALFWorld 上作为独立 agent **79.5%**，比最强 baseline **+8.8pp**，**零额外任务时 LLM 调用**；作为插件层给 retrieval-heavy baseline **+0.68 ~ +2.90pp**；当前规则版维护**几乎零库时 LLM 调用**。它还命名了一个失败模式：**skill technical debt**（冗余、缺验证、接口漂移、实现陈旧）。

---

### P5. Skill-as-Pseudocode：把正文改写成"带类型的伪代码"

*Li et al.，2026-05，[arXiv:2605.27955](https://arxiv.org/abs/2605.27955)，EMNLP Findings 2026*

**① 优化什么**
把 markdown 技能库**自动转换**成**带类型的伪代码**：从相似过程段落的聚类里抽出一个 **typed contract**，再通过**四检查的确定性验证器**（coverage / binding / replacement / risk）过滤；通过后**内联进重写的技能骨架**，并与**还原出来的 action template** 并存。

关键在于它给了 agent **两个互补信号**：一个**类型签名**（这技能干什么）+ 一个**具体调用模板**（怎么调）。这正是你说的"正文里什么都塞"的反面——把"说明"和"可执行形态"分开。

**② 怎么优化 / 前后对比**
ALFWorld unseen（134 局 / gpt-4o-mini / 3 seeds）：SaP **82/402** 配对局胜出，Graph-of-Skills 基线 47/402（pooled McNemar `p = 8.2×10⁻⁵`）；同时**输入 token −22.8±6.4%**、**每局 LLM 调用 −14.5±4.1%**。
最值得记的消融：**只给 typed contract、不给 action template，会掉到 prose baseline 以下**。→ 类型化不是越抽象越好，**必须配可执行模板**。

**③ 场景**
markdown 技能库 → 伪代码库的重构；评测在 ALFWorld unseen split。

---

### P6. AIP：把技能变成"可校验的执行图"

*Blumenfeld & Webber，2026-06，[arXiv:2606.04781](https://arxiv.org/abs/2606.04781)*

**① 优化什么**
把技能建模成**有向执行图**：**节点 = 离散步骤**（背后是确定性脚本或自然语言描述），**边 = 显式的类型化输入/输出**，整体由 **schema 校验的 YAML** 描述。另配一个 **compiler meta-skill**，把人类写的既有技能编译成这种形态。

**② 怎么优化 / 前后对比**
- 编译人类技能后（27 个来自 SkillsBench 的真实 agent 任务）：Claude Sonnet 平均任务奖励 **0.60 → 0.71**、通过率 **53% → 67%**，Wilcoxon `p = 0.011`（12 胜 2 负 13 平），且常常墙钟更短。
- 更关键的是改进闭环：因为**每个技能 schema 可校验、可功能测试、可按节点寻址**，两例失败被**追到脚本级**；调整 AIP 规格、重新编译后**零回归恢复**（其中一例从 0/5 到 5/5）。

**③ 场景与延伸**
SkillsBench 任务集；作者还指出该图天然提供**语料级治理**、**技能内省**，以及"对技能做 RL 的动作空间"。

---

### 其他（未细读，仅登记）

- **MUSE-Autoskill**（[arXiv:2605.27366](https://arxiv.org/abs/2605.27366)）：技能创建 / 记忆 / 管理 / 评估，按一份"specification"走结构化流水线。
- **Dynamic Agent Skills 综述**（[arXiv:2607.10113](https://arxiv.org/abs/2607.10113)）：提出 **skill-record schema** 与 **10 个操作符词汇表**，属于"给库更新定义统一词汇"的轻量协议。
- **Governable Individuals**（[arXiv:2607.05463](https://arxiv.org/abs/2607.05463)）：身份层，能力获取"under contract"。

---

## 3. 各家对"正文里该有什么"的提案对照

| 维度 | Agent Skills 规范 | SoK（清单） | SkillOps `P,O,A,V,F` | SaP | AIP | Selm 五元组 | VCE `⟨m,C_s⟩` |
|---|---|---|---|---|---|---|---|
| 适用/触发条件 | 仅靠 `description` 自然语言 | ✅ applicability conditions | ✅ **P** | ✅ 契约内 | ✅ 边/前置 | ✅ `trigger conditions` | ✗ |
| 操作本体 | ✗（自由正文） | ✅ execution policies | ✅ **O** | ✅ action template | ✅ 节点（脚本或描述） | ✗ | ✗ |
| 产物类型 | ✗ | ✅ reusable interfaces | ✅ **A**（类型） | ✅ typed signature | ✅ 类型化边 | ✗ | ✗ |
| 验证器 | validation（针对格式） | ✅ 隐含于 certifiable | ✅ **V** | ✅ 四检查验证器 | ✅ schema 校验 | ✗ | ✗ |
| 失败模式 | ✗ | ✅ termination criteria | ✅ **F** | ✗ | ✗ | ✗ | ✗ |
| 工具权限 | ✅ `allowed-tools`（实验） | ✅ 分级可信执行 | ✗ | ✗ | ✗ | ✗ | ✗ |
| 分块/按需加载 | ✅ 渐进披露 | ✅ 该模式被列为设计模式 | ✗ | ✅ core + template | ✅ 按节点 | ✗ | ✅ 核心/按需模块 |
| 来源与版本 | `metadata`（任意 map） | ✗ | ✗ | ✗ | ✗ | ✗ | ✅ provenance 标签 |
| 身份/生命周期 | ✗ | ✗ | 库级维护动作 | ✗ | ✗ | ✅ 库级 | ✗ |

读法：**没有任何一篇把九列填满。** 最全的是 SkillOps（结构槽位最细）与 Agent Skills（唯一有工业标准与工具权限）。

---

## 4. 为什么"没有正文协议"会拖累自进化（四条，都有证据）

1. **不可校验 → 只能拿下游分数当信号**，而 Ratchet 已经证明"用总分管库"在 judge 假通过率超过 `(1−τ)/2` 时**无论如何都退不掉任何技能**。
2. **不可归因 → 改进只能整体重写**。SkillOpt 里 rewrite 模式与 patch 模式的并存，本质就是"没有结构就只能整篇改"；而 SkillBoost 之所以能做组件级归因，靠的正是把技能拆成 `Metadata/Workflow/Constraints/References` 四个槽位。
3. **不可声明依赖 → 静默过期**。Repo2Skill-Evo 里 105 次发布迁移**每次都让部分技能失效**、过期行中位数 **92 行**——因为技能里没有"引用自哪个版本"的字段。
4. **不可比较 → 库管理只能靠启发式**。Library Drift 的 `body-hash collisions`、Selm 的 graveyard、VCE 的 `EXP-k/SELF-k` 标签，都是在**给缺失的协议打补丁**。

反过来，一旦有协议，就出现可测收益：SaP（token −22.8%、调用 −14.5%）、AIP（通过率 53%→67%，且能精修到脚本级）、SkillReducer（描述 −48%、正文 −39%，质量 +2.8%）。

---

## 5. 如果你想自己定一套：一个最小可用草案

> 下面是我的综合建议，**不是任何一篇论文的结论**，供你判断值不值得做。

把一份技能拆成"可直接加载的最小核心 + 按需模块"，frontmatter 在官方六个字段之外补四个：

```yaml
name: spreadsheet-formula-check          # 官方字段
description: ...                          # 官方字段，尽量含触发条件
version: 3                                # 新增：单调递增，回滚要靠它
source: repo@git-sha / url@date           # 新增：每条断言的来源锚（治"静默过期"）
preconditions: [输入文件存在, 语言=zh]     # 新增：可机器检查
artifacts: {type: xlsx, schema: ...}      # 新增：产物类型（治"接不上"）
validators: [重算公式, 逐格比对]           # 新增：可执行检查；无检查须显式标 none
failure_modes: [公式缓存值未更新, ...]     # 新增：失败归因的锚
```

正文三条硬约束：

1. **每个 step 要么有可执行检查，要么显式标 `check: none`**——否则下游无法判断这一步做对没有；
2. **每条事实性断言带来源锚**（`repo@commit` / URL + 日期）；
3. **正文分两级**：`core`（每次加载）与 `on-demand`（按需读），并在 core 里写清"何时去读哪个文件"。

再加两条流程约束：**淘汰/退休必须依据可观测的贡献分而不是总分**（Library Drift 的 A4 反例：证据不足就退役 = −0.019）；**验证器与被验证对象不同源**（Ratchet 的矩形可治理区）。

> 本项目已经把上面这套思路落成了具体草案：[`../skill_protocol.md`](../skill_protocol.md)（只服务"确定目标 / 执行基本动作"两个操作，且把自进化写进格式）。

---

## 6. 本次未核实

1. **Agent Skills 规范的 `validation` 与"file references"两节**：抓取在 frontmatter 后截断，具体校验规则未见。
2. **AIP 的 spec 字段全表**：只读到摘要级描述（节点 / 类型化边 / schema 校验），完整 YAML 结构在正文与附录，未读。
3. **Skillware 的本体类目与生命周期定义细节**：目前是摘要级，26 页正文未读。
4. **MUSE-Autoskill 的"specification"到底是什么形状**：未细读。
5. **是否存在跨厂商的正文协议草案**（如 AIP 与 SkillOps 是否有合并/互认迹象）：没有检索到明确证据，**不作为结论**。

---

## 7. 一句话回答你

**是，有一类工作，而且它们正在做你想做的事——但还没形成标准。** 现在能拿到的确定性是：`name`/`description` 已经被标准约束住（官方给了长度与字符集），**正文完全自由**；而 2026 年已有至少四条路线（契约槽位 / 类型化伪代码 / 执行图 / 软件本体）在补正文，并且都给出了可测收益。真正空着的是**L5：把协议约束接进自进化的接受与淘汰判据**——目前没人做。
