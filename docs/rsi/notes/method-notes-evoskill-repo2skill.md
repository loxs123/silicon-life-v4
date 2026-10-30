# 方法细节素材（两篇）

### EvoSkill v2（arXiv 2610.25931）

- **输入 / 输出**：用户给三样：benchmark 的自然语言说明（数据位置、用哪个 split、solver 拿到什么/要产出什么、run 规模）、数据集、grader 函数 `grade(task, snapshot)`（读 attempt 结束时 solver 的工作目录，返回 0–1）。产出是逐 epoch 重写的 skill 集（含 SKILL.md 的文件夹，可带脚本）；模型与 harness 不动；末轮 skill 在 held-out 上测。
- **流水线步骤**：
  1. Benchmark Adaptor（BA，Claude Code＋Sonnet 5.5）：输入用户说明＋数据＋grader；输出①冻结的 plug-in（一个 Python 模块，列出全部 task 及其 set=train/validation/test，以及 grader 要读的字段）②reference folder（除 val/test 材料与 grader 之外的全部内容）。规则：split 在写第一个 skill 之前固定；BA 须把 grader、val/held-out 信息排除在 reference folder 外，作者手工核查。
  2. Solver（同 harness；SpreadsheetBench 用 Sonnet 5.5，τ3 用 Haiku 5.5）：输入 task（首条 user message）＋当前 skill 集，经 progressive disclosure 生效——上下文常驻每个 skill 的名字和一行描述，body 仅当描述匹配任务时由 tool call 载入；输出容器内工作目录终态。每 epoch 对每个 train、val task 各试 3 次。
  3. 打分：用户提供的 grader，非 agent。SpreadsheetBench 先在 LibreOffice 重算全部公式再逐 cell 与参考簿比对；τ3 比对最终数据库状态或 action 调用。全或无：全部检查通过才得 1。
  4. Evolver（整轮 run 只有一个 stateful Claude Code session，Sonnet 5.5；两个 τ3 run 改用 Haiku 5.5）：输入 `/evo/traces/epoch_K`（训练 attempt 的 session log）、`/evo/scores/epoch_K.json`（0–1 或 grader_failed）、`/evo/solver_workspaces/epoch_K`、`/evo/skills/epoch_K`、`/evo/reference`；输出写进 `/evo/staging`（下一版 skill，起点是它上次留下的）和 `/evo/evolver_workspace`（私有笔记）。门控：只用训练材料，val/test 的 attempt 与分数由 orchestration layer 屏蔽、永不上传；每轮 skill 一律接受，无 keep-if-better。
  5. 用新 skill 集重复 2–4；末轮 skill 在 held-out 上每 task 独立跑 3 次。
- **关键超参 / 阈值**：每 task 每 epoch 3 次尝试，epoch 0 无 skill；SpreadsheetBench 每次 attempt 20 分钟墙钟＋45 turn、11 GiB 内存、禁用 web search/fetch/子 agent、只可访问模型 API；split 57 train / 57 validation / 104 held-out（297 个三类别任务过滤到 218）；τ3 为 19 / 20 / 31；held-out episodes 104×3=312（SpreadsheetBench）、31×3=93（τ3）。总 epoch 数：未找到。
- **关键设计取舍**：evolver 做成"带 bash 的 agent"而非一串单次模型调用（SkillOpt 式），且"整轮一个 session"而非每轮重开（SkillBoost 式）——session 延续使其保留先前分析。每任务给多次尝试，因为单次尝试太吵，分不清"更好的 skill"与运气；接受每轮 skill，因为在噪声分数上做 keep-if-better 会否掉好改动。evolver 只见训练材料：否则分数可靠改 split、改可见材料升高而不靠更好的 skill；v1 曾找到并利用 SpreadsheetBench grader 只比对公式旁缓存值、不重算的缺陷，故 grader 由用户提供。
- **实验设置**：SpreadsheetBench v2 三类（Debugging / Financial_Model / Template；剔除 Visualization——四类中最易且判分需视觉语言模型）；τ3-bench banking（客服对话）。Baseline：SkillOpt、SkillBoost、no-skill。指标：pass@1＝通过的 episode 占比；pass@3＝3 次中至少 1 次通过的任务占比；all@3＝3 次全通过；成本为 Claude Code 自身 list-price 对 optimizer 的估算（不含 solver）；per point＝成本 ÷ 相对 no-skill 的提升百分点。另设"仅 pass/fail"的稀疏反馈实验，只给每个训练 attempt 是否通过。
- **主要结果数字**：
  - SpreadsheetBench 细粒度真值：no skill 81/312、SkillBoost 101、SkillOpt 102、EvoSkill v2 126（比更强 baseline 高 7.7pp）；成本 $13.95 / $8.56 / $12.84，per point $2.18 / $1.27 / $0.89。
  - SpreadsheetBench 仅 pass/fail：81 / 85 / 107 / 105；成本 $13.66 / $6.65 / $0.53；EvoSkill v2 与 SkillOpt 持平而成本不足其十分之一，per point $0.07。
  - τ3 细粒度：48/93，baseline 至多 43（+5.4pp）。
  - τ3 自演化（Haiku 5.5 同时做 solver 与 evolver）：held-out 通过率提升至多 21.5pp。
  - 失败重复性：SpreadsheetBench 上 Sonnet 5.5 失败过至少一次的任务中，约十之有九三次全败；τ3 上 Haiku 5.5 约十之有六。
- **未找到的信息**：总 epoch 数；τ3 的 no-skill 起点与各 baseline 的 τ3 成本/分数（表 3）；图 2、图 4 的逐 epoch 曲线数值；表 5 的消融数字；附录 A.4/A.5 的提示词原文；skill 数量与单 skill 长度约束。

**方法要点**：把优化对象严格限制在 solver 的 skill 文件夹。BA 先冻结任务清单与 split，grader 由用户提供且全程不可被 evolver 改动；solver 每轮把每个训练/验证任务跑 3 次，evolver 作为一个贯穿全程、带 bash 的 stateful coding agent，只读训练侧轨迹、分数与 reference，直接把下一版 skill 写进 staging，全程不筛选、不淘汰；末轮 skill 才交给 held-out 打分。

---

### Repo2Skill-Evo（arXiv 2608.21964）

- **输入 / 输出**：起点是三元组（固定的 V1 skill 集 𝒮_V1、官方 V1→V2 release patch Δ、维护工具接口 𝒰_maint），该 skill 集由 Repo2Skill 蒸馏并经专家修订后冻结，所有被评测 agent 共用。产出是更新后的 V2 skill 集 𝒮_V2，评测对象是集合级变换 𝒮_V1→𝒮_V2。
- **流水线步骤**：
  1. 蒸馏 agent（Claude-opus-4.6 与 GPT-5.4 各产出一套候选，均只用 pre-release 仓库）：在状态 w_t=(H_t, A_t, L_t, M_t, S_t)（交互历史、分析报告、logic read-map、材料文档、skill 包）上跑 think–act–observe，动作空间 A_distill={analyze, logic, materials, draft, validate, finish}。analyze 先做静态分析建符号索引 I_sym（符号/文件路径→源码位置）；logic 得 routing read-map；materials 收集仓库证据；draft 写 SKILL.md（＋可选脚本、references），并记录每条断言的来源路径与符号作为外部元数据；validate 过 grounding gate；finish 仅在验证通过后终止。默认按序执行，只有失败或被拒时才回退到前序阶段。
  2. Grounding gate（validate）：核对生成的 SKILL.md 与脚本中引用的路径/符号能否在 V1 仓库中解析；对达到最小引用数的候选，一旦不可验证引用占比超过预设阈值即判失败，未通过者不进专家环节。
  3. 专家（人类）在两个候选中选较强的一套，对照 V1 仓库修订与验证；gold label 构造前冻结为 𝒮_V1。
  4. 维护 agent（单 agent scaffold：6 个通用工具覆盖 shell 执行、受限文件发现与检查、字符串编辑、终止；无任何任务特定的定位或修复模块；统一 SOP prompt；turn budget 在初始化时告知且全程报告剩余）：输入 𝒮_V1＋patch，在工作区编辑产出 𝒮_V2；预算耗尽则部分结果照评。
  5. 打分：gold obsolete set G_Δ 由自动候选发现＋行级人工对照 patch 直接证据核验；R＝𝒮_V1→𝒮_V2 diff 删除侧的 V1 行（含改写），新增 "+" 行不计；gold 行原文出现在删除侧才算 hit。Recall＝|G_Δ∩R|/|G_Δ|，Precision＝|G_Δ∩R|/|R|，F1＝2|G_Δ∩R|/(|G_Δ|+|R|)。每 transition 3 次 run 取 avg@3、best@3，再对 105 个 transition 做 macro 平均；headline＝avg@3 macro F1。R=∅ 时 recall 与 F1 记 0、precision 未定义。
  6. 补充 NL Judge：读 patch、V1 skill、𝒮_V2 与有限 run metadata，打 5 个 0–2 分——API、Files、Info（保留仍有效 guidance）、Prompt（是否遵循 patch-grounded 指令）、NL；Sum 0–10，结构非法的 skill 集 form-gate 为 0。
- **关键超参 / 阈值**：57 个公开 GitHub 仓库、105 个官方 release transition、共 1,158 个 skill；105 个 gold 集合合计 12,217 条 patch 核验的过期行，每 transition 均 |G_Δ|>0，过期行数中位数 92；每 transition 3 次独立 run；skill 候选 2 套（opus-4.6、GPT-5.4 各一）。turn budget 具体数值与 grounding gate 的"最小引用数/比例阈值"：未找到。
- **关键设计取舍**：走 minimal-edit 而非整体重写——precision 项惩罚对 G_Δ 之外 V1 行的改动，Info 维度查"仍有效的 V1 guidance 是否被保留"，因为一次性重生成会丢掉仓库特定知识。只匹配删除侧、不查新增 "+" 行，因为合法的 V2 替代可能有多种语义等价写法，故最终态质量交给 NL Judge。刻意用极简 scaffold（6 个通用工具、无定位/修复模块），以便把差异归因到模型行为；并把维护对象定为"agent 面向的 guidance 而非仓库代码"，因为它是独立 artifact，维护不会退化成 code migration。
- **实验设置**：105 个官方 V1/V2 tag 配对的 release transition（聚焦 AI/ML 与 LLM-agent 生态，兼顾若干成熟通用库，优先选源码级改动明显、可能影响仓库特定流程知识的 transition）；每 transition 一套冻结 V1 skill。Baseline：6 个 frontier agent 在同一 scaffold、同一 SOP、同一 turn budget 下横向对比。指标如上（avg@3 macro F1、macro recall、macro precision，另 best@3 与 NL Judge Sum 0–10）；附 10 个随机抽样仓库的 utility study、20 个最难 transition 的 oracle skill-file localization 消融。
- **主要结果数字**：本文无"改造前/改造后"对照，主结果是维护成绩本身——6 个 frontier agent 的 avg@3 macro F1 仅 29.9%–69.7%；每个被选 transition 的 V1 skill 集都含 patch 核验的过期内容（中位数 92 行）；两类错误互补：skill 集覆盖不全导致过期内容未被触碰，编辑过宽则 recall 升高而 precision 下降；20 个最难 transition 上给 oracle 文件级定位可提升，但仍残留大量错误。
- **未找到的信息**：6 个 agent 的具体模型名与逐项数字（表 4.x）；turn budget 数值；grounding gate 的最小引用数与阈值；utility study 与消融的具体数字（§4.2、§4.4、§10）；NL Judge 五维得分（§11.1）；仓库清单与领域分布细节。

**方法要点**：把"仓库 skill 过期"做成可评测的维护任务：先用分阶段蒸馏（analyze→logic→materials→draft→validate）加引用可解析的 grounding gate 产出并冻结 V1 skill 集，再让单 agent 在最小工具集下依据官方 patch 只改过期部分、保留仍有效内容；评分只认 patch 核实过的过期行被删除或改写，用 recall/precision/F1 平衡漏改与过度编辑，语义正确性另交五维 NL Judge。

---

抓取说明：两篇 arXiv HTML 全文在固定字符上限处被截断（EvoSkill v2 读到 §5.2 开头，Repo2Skill-Evo 读到 §4.1 中段），export/browse-export 镜像、分节锚点、文本代理均未取得更后章节；因此上列"未找到"项部分属于抓取不可达，而非论文未写。
