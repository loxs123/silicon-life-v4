from .optimize_skill  import hook as skill_hook
from .optimize_memory import hook as memory_hook

HOOKS = [
    skill_hook,
    memory_hook
]