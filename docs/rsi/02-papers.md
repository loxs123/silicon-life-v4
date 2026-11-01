# RSI 文献清单（可检索索引）

> 按主题分组，不按时间排序。**关键结果**一列只写论文摘要/官方页面明确给出的数字，未核实的数字一律留空或写"—"。
> 分层缩写：**L0** 提示 ｜ **L1** 脚手架代码 ｜ **L2** 技能/记忆 ｜ **L3** 元机制 ｜ **L4** 权重 ｜ **L5** 训练/硬件 ｜ **T** 理论 ｜ **S** 安全 ｜ **R** 综述/基准

## 一、思想史与理论（T）

| 年份 | 工作 | 关键结果 / 内容 | 链接 |
|---|---|---|---|
| 1965 | Good, *Speculations Concerning the First Ultraintelligent Machine* | 提出智能爆炸与"最后一个发明"论证 | [dblp](https://dblp.org/rec/journals/ac/Good65.html) |
| 1993 | Vinge, *The Coming Technological Singularity* | 三十年出现超人类智能的工程预测 | [ADS](https://ui.adsabs.harvard.edu/abs/1993vise.nasa...11V) |
| 2003 | Schmidhuber, *Gödel Machines* | 可证明有益的自我重写；无局部最优；实践不可行的起点 | [arXiv:cs/0309048](https://arxiv.org/abs/cs/0309048) |
| 2010 | Chalmers, *The Singularity: A Philosophical Analysis* | 拆解奇点论证的前提 | — |
| 2013 | Yudkowsky, *Intelligence Explosion Microeconomics* | 用边际回报判断是否会爆炸 | [MIRI](https://intelligence.org/2013/04/29/intelligence-explosion-microeconomics-released/) |
| 2014 | Bostrom, *Superintelligence* | seed AI；RSI 作为路径之一 | — |
| 2016 | Walsh, *The Singularity May Never Be Near* | 反方：回报递减与约束 | [ar5iv](https://ar5iv.labs.arxiv.org/html/1602.06462) |
| 2020 | Real et al., *AutoML-Zero* | 进化搜索从近空白程序重新发现基础算法 | — |

## 二、脚手架级自我改进（L1）

| 年份 | 工作 | 关键结果 | 链接 |
|---|---|---|---|
| 2023 | **STOP**: Self-Taught Optimizer（COLM 2024） | 改进器改进自身；自行提出束搜索/遗传算法/退火；测量了沙箱绕过频率；自认"非完整 RSI" | [2310.02304](https://arxiv.org/abs/2310.02304) |
| 2024 | **ADAS**: Automated Design of Agentic Systems（ICLR 2025） | 元 agent 在代码空间搜索新架构并归档 | [2408.08435](https://arxiv.org/abs/2408.08435) |
| 2024 | **Gödel Agent**（ACL 2025） | 提示驱动的自我逻辑改写，无需预设优化算法 | [2410.04444](https://arxiv.org/abs/2410.04444) |
| 2025 | **SICA**: A Self-Improving Coding Agent | SWE-bench Verified 子集 17% → 53%；非梯度、数据高效 | [2504.15228](https://arxiv.org/abs/2504.15228) |
| 2025 | **DGM**: Darwin Gödel Machine | SWE-bench 20.0→50.0；Polyglot 14.2→30.7；archive + 开放式探索；沙箱+人审 | [2505.22954](https://arxiv.org/abs/2505.22954) |
| 2026 | **Hyperagents / DGM-H** | 任务 agent 与元 agent 合成单一可编辑程序；元层修改过程本身可编辑；跨域迁移 | [2603.19461](https://arxiv.org/abs/2603.19461) |
| 2026 | **SpecRSI**: 推测式 RSI | 前驱未评估完先起草后继、完整验证后采纳；VATS 预算分配；对 Janus/MetaRSI/HGM 的对照 | [2610.16491](https://arxiv.org/abs/2610.16491) |

## 三、进化 + 评估器（L5 / L1）

| 年份 | 工作 | 关键结果 | 链接 |
|---|---|---|---|
| 2024 | **FunSearch**（Nature） | LLM 提议 + 评估器打分 + 程序库；cap set、装箱问题新结果 | [Nature](https://www.nature.com/articles/s41586-023-06924-6) |
| 2025 | **AlphaEvolve** | 4×4 复数矩阵乘法 48 次标量乘法（56 年来首次改进 Strassen 该设定）；数据中心调度（博客称约 0.7% 全球算力）；电路功能等价化简；加速训练自身的模型算子 | [2506.13131](https://arxiv.org/abs/2506.13131)｜[博客](https://deepmind.google/discover/blog/alphaevolve-a-gemini-powered-coding-agent-for-designing-advanced-algorithms/) |
| 2025 | **ShinkaEvolve** | 样本高效的开放式程序进化 | [Sakana](https://sakana.ai/shinka-evolve/) |
| 2026 | **GEPA**（ICLR 2026） | 反思式提示进化，可超过强化学习调参 | [proceedings](https://proceedings.iclr.cc/paper_files/paper/2026/hash/0e9e708b6f48e14fd0ac29e167413f76-Abstract-Conference.html) |
| 2024 | **TextGrad** | 用文本"梯度"做系统级优化 | — |

## 四、元机制与评估器（L3）—— 本领域最新前沿

| 年份 | 工作 | 关键结果 | 链接 |
|---|---|---|---|
| 2026 | **Who Verifies the Verifier?**（NeurIPS 2026 WS） | 把验证器变成进化对象；MBPP+ 上留出集一致性 +0.21；**坍缩成"永远判过"的空评器也能训出同样好的技能** | [2610.11464](https://arxiv.org/abs/2610.11464) |
| 2026 | **LLM-as-a-Judge Is Not an Oracle** | 生产环境 11 种评估失效；100% 通过率掩盖 68% 真实能力；PROCTOR 五道确定性护栏 | [2609.02246](https://arxiv.org/abs/2609.02246) |

## 五、权重级自我改进（L4）

| 年份 | 工作 | 关键结果 | 链接 |
|---|---|---|---|
| 2022 | **STaR** | 自生成理由 + 保留正确答案，自举推理 | [2203.14465](https://arxiv.org/abs/2203.14465) |
| 2024 | **Self-Rewarding LMs**（ICML 2024） | LLM 自评分 + 迭代 DPO；指令跟随与评分能力同时提升 | [2401.10020](https://arxiv.org/abs/2401.10020) |
| 2024 | **SPIN** | 自博弈式微调，区分自产与人类数据 | [2401.01335](https://arxiv.org/abs/2401.01335) |
| 2025 | **SEAL** | 自生成"自编辑"→ SFT 持久改权重；用下游表现做 RL 奖励 | [2506.10943](https://arxiv.org/abs/2506.10943) |
| 2025 | **Absolute Zero / AZR** | 零数据自博弈：自出题、自解、自验证 | [2505.03335](https://arxiv.org/abs/2505.03335) |

## 六、技能与记忆（L2）

| 年份 | 工作 | 关键结果 | 链接 |
|---|---|---|---|
| 2023 | **Reflexion** | 语言化反思写入记忆，改善后续尝试 | [2303.11366](https://arxiv.org/abs/2303.11366) |
| 2023 | **Voyager** | 技能库持续积累，开放式探索 | [2305.16291](https://arxiv.org/abs/2305.16291) |
| 2026 | **AREX** | 内外双循环（研究 + 自我改进）；学得"自主上下文更新工具"压缩改进状态；4B / 122B-A10B | [2607.21461](https://arxiv.org/abs/2607.21461) |

## 七、垂域扩展

| 年份 | 工作 | 关键结果 | 链接 |
|---|---|---|---|
| 2024 | **The AI Scientist** | 提想法—实验—写作—自评审全流程 | [2408.06292](https://arxiv.org/abs/2408.06292) |
| 2026 | **RSI-Anything** | 世界模型指导 RSI；代码修复 26.3→31.2；实验室规划 21.8→46.0；反应优化 96.15 vs BO 82.16 | [2610.13912](https://arxiv.org/abs/2610.13912) |
| 2026 | **SEAR**: Self-Evolving Agentic Robotics | 机器人领域的自进化 agent | [2610.18792](https://arxiv.org/abs/2610.18792) |

## 八、反证与限制

| 年份 | 工作 | 关键结果 | 链接 |
|---|---|---|---|
| 2024 | Huang et al., *LLMs Cannot Self-Correct Reasoning Yet*（ICLR 2024） | 无外部反馈时自我纠正常导致性能下降 | — |
| 2024 | Kamoi et al., *When Can LLMs Actually Correct Their Own Mistakes?*（TACL） | 可靠自纠依赖外部信息 | [ACL](https://aclanthology.org/2024.tacl-1.78.bib) |
| 2024 | Shumailov et al., *AI models collapse when trained on recursively generated data*（Nature 631） | 自产数据递归训练导致分布尾部消失 | [Nature](https://www.nature.com/nature/volumes/631/issues/8022) |
| 2026 | *On the estimation and validity of AI time horizons* | 对 METR 型时间跨度曲线的统计质疑 | [2610.12466](https://arxiv.org/abs/2610.12466) |

## 九、安全

| 年份 | 工作 | 关键结果 | 链接 |
|---|---|---|---|
| 2019 | Hubinger et al., *Risks from Learned Optimization* | mesa-optimization 与欺骗性对齐的理论框架 | [1906.01820](https://arxiv.org/abs/1906.01820) |
| 2024 | Greenblatt et al., *Alignment faking in LLMs* | Claude 3 Opus：免费用户 14% 顺从 vs 付费几乎 0；RL 后伪装推理升至 78%；出现权重外泄行为 | [2412.14093](https://arxiv.org/abs/2412.14093) |
| 2025 | OpenAI Preparedness Framework v2 | 把 AI self-improvement 列为独立风险类别 | [说明](https://openai.com/index/updating-our-preparedness-framework/)｜[PDF](https://cdn.openai.com/pdf/18a02b5d-6b67-4cec-ab64-68cdfbddebcd/preparedness-framework-v2.pdf) |
| 2025 | Anthropic RSP v3 | 以 AI R&D 能力等级作为阈值 | [RSP](https://www.anthropic.com/responsible-scaling-policy) |

## 十、综述与基准（R）

| 年份 | 工作 | 关键结果 | 链接 |
|---|---|---|---|
| 2026 | Gao et al., *A Survey of Self-Evolving Agents*（TMLR 2026, 77 页） | what/when/how/where to evolve 四维框架 | [2507.21046](https://arxiv.org/abs/2507.21046) |
| 2026 | **SEA-Eval** | 首个自进化 agent 专用基准；同成功率下 token 消耗最高差 31.2×；提出"能力幻觉" | [2604.08988](https://arxiv.org/abs/2604.08988) |

---

## 十一、Skill 协议层（定义格式，不优化技能）

> 展开分析见 [`04-skill-protocol.md`](04-skill-protocol.md)。

| 年份 | 工作 | 关键结果 | 链接 |
|---|---|---|---|
| 2025 | **Agent Skills 规范**（开放标准） | 定死外壳：目录 + frontmatter 六字段（`name` ≤64 字符、`description` ≤1024、`license`、`compatibility` ≤500、`metadata`、`allowed-tools` 实验）+ 渐进披露 + validation；**正文仍自由 Markdown** | [agentskills.io](https://agentskills.io/specification) |
| 2026 | **SoK: Agentic Skills** | 把 skill 定义为"过程知识 + 适用条件 + 执行策略 + 终止条件 + 可复用接口"；七种设计模式 + representation×scope 分类；ClawHavoc 案例：约 1,200 个恶意技能渗入市场；结论指向可验证、可认证 | [2602.20867](https://arxiv.org/abs/2602.20867) |
| 2026 | **Skillware** | 软件本体论：Skill Artifact / Skillware Unit / Agent Host；三个必要条件 + **Lifecycle Continuity**；证据含 138,133 条去重 SKILL.md（20,556 个仓库） | [2607.18970](https://arxiv.org/abs/2607.18970) |
| 2026 | **SkillOps** | 类型化 **Skill Contract `(P,O,A,V,F)`** = 前置条件/操作/产物类型/验证器/失败模式；HSEG 四类类型化边；五维库健康；ALFWorld 79.5%（+8.8pp），库时近零 LLM 调用 | [2605.13716](https://arxiv.org/abs/2605.13716) |
| 2026 | **Skill-as-Pseudocode（SaP）** | markdown → 带类型伪代码 + 四检查确定性验证器；ALFWorld unseen 配对胜 82/402 vs 47/402（p=8.2e-5），输入 token −22.8%、调用 −14.5%；**只有契约没有模板会低于 prose 基线** | [2605.27955](https://arxiv.org/abs/2605.27955) |
| 2026 | **AIP: Agent Instruction Protocol** | 技能 = 有向执行图（节点为脚本或描述、边为类型化 I/O）+ schema 校验 YAML；27 个 SkillsBench 任务上奖励 0.60→0.71、通过率 53%→67%（p=0.011）；失败可定位到脚本级并零回归修复 | [2606.04781](https://arxiv.org/abs/2606.04781) |
| 2026 | **MUSE-Autoskill** | 技能创建/记忆/管理/评估的结构化流水线 | [2605.27366](https://arxiv.org/abs/2605.27366) |
| 2026 | **Governable Individuals** | 身份层，"能力获取 under contract" | [2607.05463](https://arxiv.org/abs/2607.05463) |

## 十二、技能自进化（Skill Self-Evolution，L2）

> 展开分析见 [`03-skills.md`](03-skills.md)。

| 年份 | 工作 | 关键结果 | 链接 |
|---|---|---|---|
| 2026 | **Dynamic Agent Skills**（TMLR 2026） | 124 篇 2023–2026 审计；六种 skill 形态 + 八阶段生命周期；指出 flat retrieval 随库增长退化、基准少报库轨迹/usage–utility/安全面 | [2607.10113](https://arxiv.org/abs/2607.10113) |
| 2026 | **SkillsBench**（NeurIPS 2026） | 87 任务 / 8 域 / 18 配置配对实验；人工技能 33.9%→50.5%（+16.6pp）；≤3 模块的聚焦技能更优 | [2602.12670](https://arxiv.org/abs/2602.12670) |
| 2026 | **SkillOpt** | 把技能当"冻结 agent 的外部状态"来训练；有界增删改 + 留出严格提升才接受；52 个单元全最优/并列；GPT-5.5 上 +23.5/+24.8/+19.1pp（chat/Codex/Claude Code） | [2605.23904](https://arxiv.org/abs/2605.23904) |
| 2026 | **SkillBoost** | 探索-利用张力 → 结构化利用 + 先验探索 + 回归界内验收；23 个配置 SOTA，缓解过拟合 | [2607.26643](https://arxiv.org/abs/2607.26643) |
| 2026 | **VCE-Skill** | 用公共技能版本变更历史作"进化先验"，与轨迹互补；平均分 +3.20~+4.98；跨模型迁移更好 | [2608.16544](https://arxiv.org/abs/2608.16544) |
| 2026 | **SkillReducer** | 直接优化 routing layer：description 压缩 48%（含为 26.4% 缺描述者生成）、body 压缩 39%、功能质量 +2.8%；实证 55,315 个公开技能 | [2603.29919](https://arxiv.org/abs/2603.29919) |
| 2026 | **MetaSkill-Evolve** | 双时间尺度：task skill + meta-skill `(ψ,σ,α,π,ε)` 五分量参数化改进流水线；OfficeQA +23.54、SealQA +16.09、ALFWorld +1.92 | [2607.05297](https://arxiv.org/abs/2607.05297) |
| 2026 | **SkillOS** | 冻结执行器 + 可训练 curator + SkillRepo；技能自发演化为结构化 Markdown 与 meta-skill；跨 backbone/域泛化 | [2605.06614](https://arxiv.org/abs/2605.06614) |
| 2026 | **EvoSkill v2** | 三 agent（基准适配器/solver/有状态 evolver）；超 SkillOpt 与 SkillBoost 7.7pp（SpreadsheetBench v2）、5.4pp（τ³ banking）；Haiku 级自改进 +21.5pp | [2610.25931](https://arxiv.org/abs/2610.25931) |
| 2026 | **EvoSkill v1** | 多 agent 系统的自动化技能发现 | [2603.02766](https://arxiv.org/abs/2603.02766) |
| 2026 | **Library Drift**（ICML 2026 FAGEN） | 定义"库漂移"；LLM 自写技能 +0.0pp vs 人工 +16.2pp；治理配方使 0.258→0.584（+0.328，100 轮）；消融：禁用注入 +0.002、过早退休 −0.019 | [2605.19576](https://arxiv.org/abs/2605.19576) |
| 2026 | **Ratchet** | 可证界限：judge 假通过率 ≥ (1−τ)/2 时任何样本量都退不掉技能；终局分数最多只反映治理增益的 1/5 且不单调 | [2605.22148](https://arxiv.org/abs/2605.22148) |
| 2026 | **Selm** | 库级管理：效用感知检索 + Map-Reduce 定向更新 + 生命周期控制；4 个基准多数领先 | [2610.24630](https://arxiv.org/abs/2610.24630) |
| 2026 | **Repo2Skill-Evo** | 57 仓库 / 105 次发布迁移；每次迁移都使部分 V1 技能失效；六个前沿 agent 仅 29.9%–69.7% macro F1；"静默陈旧" | [2608.21964](https://arxiv.org/abs/2608.21964) |
| 2025 | **Agent Skills**（Anthropic） | `SKILL.md` + 渐进式披露三层；可捆绑可执行代码；2025-12 开放为跨平台标准 | [博客](https://www.anthropic.com/engineering/equipping-agents-for-the-real-world-with-agent-skills)｜[agentskills.io](https://agentskills.io/) |
| 2023 | **Voyager** | 技能库 + 开放式探索的早期原型 | [2305.16291](https://arxiv.org/abs/2305.16291) |
| 2023 | **Reflexion** | 语言化反思写入记忆 | [2303.11366](https://arxiv.org/abs/2303.11366) |
| 2024 | **Agent Workflow Memory** | 经验归纳成可复用工作流 | [2409.07429](https://arxiv.org/abs/2409.07429) |

## 待补清单（下一步值得找原文核实的点）

1. DGM 的安全章节：agent 变体是否出现过"移除自身安全约束"的尝试，以及作者如何处置。
2. SICA 的具体实验规模（子集大小、预算、基线模型）。
3. SEA-Eval 的 T 序列定义与"进化稳定性"指标的具体计算方式。
4. AlphaEvolve 博客中除 48 次乘法外的具体百分比数字（本报告只引用了摘要可确证的部分）。
5. SpecRSI 中 Janus / MetaRSI / HGM 三个基线的出处与各自定位。
6. 是否存在 2026 年的独立复现工作，验证 DGM 的 20→50% 在更换基础模型后是否成立。
