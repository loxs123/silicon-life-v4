from .optimize_skill  import hook as skill_hook
from .optimize_memory import hook as memory_hook
from .snapshot import hook as snapshot_hook

HOOKS = [
    skill_hook,
    memory_hook,
    snapshot_hook
]