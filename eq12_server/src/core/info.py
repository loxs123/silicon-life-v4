from dataclasses import dataclass, field


@dataclass
class Info:
    queues: dict = field(default_factory=dict)
    goals: list = field(default_factory=list)
    cur_memories: list = field(default_factory=list)
    cur_goal: object = None
    cur_skill: object = None
    context: list = field(default_factory=list)
    action: object = None
    output: object = None
    loaded: bool = False
