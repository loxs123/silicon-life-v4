## 日志

一行一个 JSON，字段固定四个：`type`、`content`、`time`、`goal`。
`goal` 是这条记录属于哪个目标（goal-id，整数）；`queue-msg` 没有 `goal`，它属于队列不属于目标。
`content` 是对象（不是字符串），结构见 `hooks/protocols-json/`。

### 存储目标
{"type": "create-goal", "content": {"id": 1, "name": "今天还没有计划", "content": "…", "child-goals": [], "father-goal-id": null, "create-time": "xxxx-xx-xx xx:xx:xx", "finish-time": ""}, "time": "xxxx-xx-xx xx:xx:xx", "goal": 1}

### 目标开始
{"type":"start-goal", "content": {}, "time": "xxxx-xx-xx xx:xx:xx", "goal": 123}

### 目标结束
{"type":"finish-goal", "content": {}, "time": "xxxx-xx-xx xx:xx:xx", "goal": 123}

### 等待消息
{"type":"wait-message", "content": {"id": 1, "msg-type": "screen"}, "time": "xxxx-xx-xx xx:xx:xx", "goal": 123}

### 消息到达
{"type":"receive-message", "content": {"id": 1}, "time": "xxxx-xx-xx xx:xx:xx", "goal": 123}

### 确认是否完成目标目标
{"type": "check-goal", "content": {"done": 1, "reason": "可选"}, "time": "xxxx-xx-xx xx:xx:xx", "goal": 1}

### 存储记忆
{"type":"create-memory", "content": {"id": 3, "name": "…", "tags": [], "description": "…", "content": "…", "time": "xxxx-xx-xx xx:xx:xx"}, "time":"xxxx-xx-xx xx:xx:xx", "goal": 123}

### 检索记忆
{"type": "retrieve-memory", "content": {"memory-ids": [1, 3]}, "time":"xxxx-xx-xx xx:xx:xx", "goal": 123}

### 创建技能
{"type":"create-skill", "content": {"id": 2, "type": "原子动作", "name": "…", "tags": [], "description": "…", "target": "…", "steps": [], "notes": [], "verify": "…", "output": "…"}, "time":"xxxx-xx-xx xx:xx:xx", "goal": 123}

### 检索技能
{"type": "retrieve-skill", "content": {"skill-ids": ["plan"]}, "time":"xxxx-xx-xx xx:xx:xx", "goal": 123}

### 队列中的消息
{"type": "queue-msg", "content": {"queue": "asr", "type": "text", "text": "你好呀"}, "time":"xxxx-xx-xx xx:xx:xx"}

### 原子动作
{"type": "atom-action", "content": {"atom_actions": [{"queue": "tts", "text": "你好呀"}]}, "time":"xxxx-xx-xx xx:xx:xx", "goal": 123}

eq12_server\src\core\hooks\logs 每天一个日志文件 放在这个目录

## user_info 数据结构

### goal_tree

今日的目标树
```python
[
    {"goal-id": xxx, "goal-name": "xxx", "goal-path":"xxx"}, # 单项格式同 protocols-json/goal.json
    ...
]
```

### cur_goal_id

当前要完成的goal-id
```python
3
```

### cur_memories

```python
[
    {"memory-id": xxx, "memory-name": "xx", "memory-tags": [],  "memory-path":"xxx"}, # 单项格式同 protocols-json/memory.json
    ...
]
```

### cur_goal_context

```python
[
    # memory 可选
    # goal
    # skill
    # action
    # queue-msg
    # goal-checker
    # action
    # queue-msg
    # ...
]
```

memory.py
goal.py
skill.py
action.py -> 原子动作 异步总结 （如果有原子动作同时必须要加入监控）
          -> 创建子目标 同步执行goal_checker
输出两个 1. 动作 2. 是否需要goal_checker
valid.py 检查目标是否完成
memory_save.py 异步保存记忆

用来组装属于自己的那部分


