from .plan import hook as plan_hook
from .goal import hook as goal_hook
from .skill import hook as skill_hook
from .memory import hook as memory_hook

# 制定 goal → 选/造 skill → 完成 goal（多轮）→ 下一个 goal；goal 完成后写 memory
HOOKS = [plan_hook, goal_hook, skill_hook, memory_hook]
