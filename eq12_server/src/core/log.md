# 日志与每日快照（log）

> 状态：**设计稿**。`src/core/log.py` 还没写，hook 也还没接线；本文件是落地时的依据，
> 写完代码回来更新这里。

## 0. 一句话

`src/core/hooks/` 下三个并列文件夹分工：

| 文件夹 | 形态 | 内容 |
|---|---|---|
| `hooks/logs/` | **每天一个文件** `YYYY-MM-DD.log` | 当天的操作流水，**一行一个操作**，只追加 |
| `hooks/memory/` | **每天一个文件夹** `YYYY-MM-DD/` | 当天的记忆（`self.md`、`experience.md` …） |
| `hooks/skills/` | **每天一个文件夹** `YYYY-MM-DD/` | 当天的技能（一个 skill 一个 md） |

`memory/` 和 `skills/` 的当天文件夹 = **前一天的副本**（第二天开张时复制），所以它们既
是"当前状态"，也天然是"历史版本"。`logs/` 不需要复制 —— 每天新开一个空文件。

## 1. 为什么这么设计

| 原则 | 落实方式 |
|---|---|
| 模型可见 = 已落日志（见 `readme.md`） | 凡是模型读得到、改得动的动作，都写进当天的 `logs/YYYY-MM-DD.log` |
| 每天一份 = 免费的历史版本 | 想回看"上周三我的技能长什么样"，直接进 `skills/2025-06-03/` |
| 三种内容分工明确 | `logs` = 发生过什么（只追加）｜`memory` = 当前认知｜`skills` = 当前能力 |

⚠️ **log 只追加，永不修改**；memory / skills 是"当前状态"，log 是"状态是怎么变来的"。
不要把 log 当记忆用（别指望在里面"改"东西），也不要把每天的流水塞进 `experience.md`。

## 2. 目录布局

```
eq12_server/src/core/hooks/
├── logs/                        # 日志：每天一个文件
│   ├── .gitkeep
│   ├── 2025-06-01.log           # 一行一个操作
│   └── 2025-06-02.log
├── memory/                      # 记忆：每天一个文件夹
│   ├── seed/                    # 第 0 天的模板（跟着代码走）
│   │   ├── self.md
│   │   └── experience.md
│   ├── 2025-06-01/              # 第一天：从 seed 复制
│   │   ├── self.md
│   │   └── experience.md
│   └── 2025-06-02/              # 第二天：从 06-01 复制，然后在这一份上继续改
├── skills/                      # 技能：每天一个文件夹
│   ├── readme.md                # skill 的格式说明（不是当天的技能）
│   ├── seed/                    # 第 0 天（可放一两个初始 skill）
│   ├── 2025-06-01/
│   └── 2025-06-02/
├── goal.py  memory.py  skill.py  system.py    # 白天 hook
└── __init__.py
```

- **代码里只写"当天的"**：`memory_dir() / 'self.md'`、`skills_dir() / 'reminder.md'`、
  写日志走 `log(...)`（自己找当天的文件名），日期由 `log.py` 统一算，hook 里不出现日期。
- `seed/` 是唯一跟着代码版本走的部分；`YYYY-MM-DD` 这些是运行时状态（见 §8 的 gitignore）。

## 3. 日切（第二天复制前一天）

规则一条：**访问当天的 memory / skills 目录时，如果它不存在，就把最近一天的目录
（没有就用 `seed/`）复制过来。**

```python
def _day_dir(kind, date=None):            # kind = 'memory' | 'skills'
    root = HOOKS / kind
    d = root / (date or time.strftime('%Y-%m-%d'))
    if not d.exists():
        prev = 最近一个存在的日期目录(root) or (root / 'seed')
        shutil.copytree(prev, d, dirs_exist_ok=True)
        log('day', 'roll', {'kind': kind, 'from': prev.name})
    return d
```

- **不挂后台定时器**：谁用谁触发，跨过零点后的第一个动作就把目录切过去。
- **logs 不参与日切**：`log()` 发现当天的文件不存在就建一个空的，不需要复制。
- ⚠️ **dream 跨午夜**：夜间链 23:00–07:00 会跨过 00:00 —— 当前选择是**不 pin 日期**：
  零点前的改动落在 06-01，零点后的落在 06-02。想改就让 `DreamPipeline` 开头
  `log.pin('2025-06-01')`、结束时放开，代价是多一个状态。

## 4. `logs/YYYY-MM-DD.log` 格式

**一行 = 一个操作**，每行一个 JSON 对象，字段固定 6 个：

```jsonl
{"t":"12:03:11","kind":"llm","who":"brain.llm_stream","arg":{"model":"qwen-plus","messages":3,"tok_in":812},"out":"你好呀。","ms":1420}
{"t":"12:05:40","kind":"skill","who":"skill.write","arg":{"path":"reminder.md","op":"create","lines":18},"out":"ok","ms":12}
{"t":"12:07:02","kind":"memory","who":"memory.append","arg":{"path":"experience.md","op":"append","chars":64}}
{"t":"12:09:30","kind":"tool","who":"delay","arg":{"text":"提醒我喝水","in":900}}
{"t":"12:09:31","kind":"io","who":"pub/face","arg":{"payload":"think"}}
{"t":"00:00:02","kind":"day","who":"roll","arg":{"kind":"memory","from":"2025-06-01"}}
```

| 字段 | 必填 | 含义 |
|---|---|---|
| `t` | ✓ | `HH:MM:SS`（日期就是文件名，行里不重复记） |
| `kind` | ✓ | 类别，见 §5 |
| `who` | ✓ | 谁干的：hook 名 / worker 名 / 队列名 |
| `arg` | | 入参摘要（dict，会被截断） |
| `out` | | 结果摘要（一句话，会被截断） |
| `ms` | | 耗时毫秒（LLM / 工具调用才有） |

- **一行一个 JSON**：追加写天然安全、`grep` 直接能用、`json.loads` 一行一个，不怕多行
  内容破坏结构；同时往控制台同步打一行人读的：
  ```
  [log] 12:05:40 skill skill.write → reminder.md (create, 18 行)
  ```
- **截断**：`arg` / `out` 各最多 300 字，超了补 `…(+N)`。一条 LLM 回复不能撑爆日志。
- **不记敏感内容**：`DASHSCOPE_API_KEY`、飞书 `app_secret` / `tenant_access_token`、
  原始音频、base64 图片一律不写（音频只记字节数，图片只记尺寸 + 字节数）。
- **并发**：多个 worker 线程都会写 → `threading.Lock()` + `with open(..., 'a')` 追加。
