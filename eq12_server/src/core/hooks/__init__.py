from .loader import hook as loader_hook
from .goal import hook as goal_hook
from .skill import hook as skill_hook
from .memory import hook as memory_hook
from .action import hook as action_hook
from .valid import hook as valid_hook
from .memory_creator import hook as mc_hook

HOOKS = [loader_hook, goal_hook,skill_hook, memory_hook,action_hook,valid_hook,mc_hook]
