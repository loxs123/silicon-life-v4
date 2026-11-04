from dataclasses import dataclass, field


@dataclass
class Info:
    queues: dict = field(default_factory=dict)
    memory: list = field(default_factory=list)
    goals: list = field(default_factory=list)
    cur_goal: object = None
    cur_skill: object = None
    context: list = field(default_factory=list)
    action: object = None
    output: object = None
