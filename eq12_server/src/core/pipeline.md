
# 处理流程

## 主流程
```mermaid
flowchart TD
    A["创建每日目标"]
    D["读取队首目标"]
    B["检索合适的skill"]
    C{"检索结果"}

    F["调用skill-creator创建skill"]
    G["调用skill执行"]
    H["利用目标判断是否完成"]

    I{"判断结果"}

    L["异步调用memory-creator保存经历"]

    A --> D
    D --> B
    B --> C
    C -->|有合适的skill|G
    C -->|无合适的skill|F
    F --> G
    G --> H
    H --> I
    I -->|没有完成目标+未完成目标原因|G
    I -->|完成目标|L
    L -->D
```


## 打断流程
```mermaid
flowchart TD
    A["人发消息"]
    B["goal-adjustor调整目标队列"]
    A --> B
```


## 创建每日目标

### context
```markdown
1. 昨日记忆 （待定）
2. 创建目标skill
```

### effect

目标队列
```markdown
target1, target2, ...
```

日志
```json
{"type":"create targets", "content":"[]"}
```

### 检索合适的skill

### context
```markdown
1. 检索模版
2. 当前目标
```


