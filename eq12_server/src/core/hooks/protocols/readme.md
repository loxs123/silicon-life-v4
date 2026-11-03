## 日志

### 存储目标
{"type": "create-goal", "content": "格式见goal.xml", "time": "xxxx-xx-xx xx:xx:xx"}

### 目标开始
{"type":"start-goal", "content": "<goal-id>123</goal-id>", "time": "xxxx-xx-xx xx:xx:xx"}

### 目标结束
{"type":"finish-goal", "content": "<goal-id>123</goal-id>", "time": "xxxx-xx-xx xx:xx:xx"}

### 确认是否完成目标目标
{"type": "check-goal", "content": "<goal><goal-id>1</goal-id><done>1</done><reason>可选</reason></goal>", "time": "xxxx-xx-xx xx:xx:xx"}

### 存储记忆
{"type":"create-memory", "content":"格式见memory.xml", "time":"xxxx-xx-xx xx:xx:xx"}

### 检索记忆
{"type": "retrieve-memory", "content":"<goal-id>相关的目标id<goal-id><memory-ids><id>1</id></memory-ids>"}

### 创建技能
{"type":"create-skill", "content":"格式见skill.xml", "time":"xxxx-xx-xx xx:xx:xx"}

### 检索技能
{"type": "retrieve-skill", "content":"<goal-id>相关的目标id<goal-id><skill-ids><id>1</id></skill-ids>", "time":"xxxx-xx-xx xx:xx:xx"}

### 队列中的消息
{"type": "queue-msg", "content":"格式见queue.xml", "time":"xxxx-xx-xx xx:xx:xx"}

### 原子动作
{"type": "atom-action", "content":"格式见atom_action.xml", "time":"xxxx-xx-xx xx:xx:xx"}


## user_info 数据结构

### goal_tree

今日的目标树
```python
[
    {"goal-id": xxx, "goal-name": "xxx", "goal-path":"xxx"}, # 单项格式同 queue.xml
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
    {"memory-id": xxx, "memory-name": "xx", "memory-tags": [],  "memory-path":"xxx"}, # 单项格式同 memory.xml
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
goal_checker.py 检查目标是否完成
memory_save.py 异步保存记忆

用来组装属于自己的那部分


