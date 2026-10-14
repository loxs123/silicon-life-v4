from .optimize_skill  import hook as skill_hook
from .optimize_system import hook as system_hook
from .optimize_memory import hook as memory_hook

HOOKS = [
    skill_hook,
    system_hook,
    memory_hook
]