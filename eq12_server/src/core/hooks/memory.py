import re

from ..info import Info
from .tools import log
from .tools.llm_client import SELF, call_llm, context
from .tools.loader import MemoryLoader

ASK = '从「我记得的事」里挑出和当前目标相关的：一行回一个 name；都不相关就回 0。'


def _by_names(out):
    names = {line.strip(' -*.。；;') for line in out.splitlines() if line.strip()}
    return [m for m in MemoryLoader.all() if m._id != SELF and m.name in names]


def hook(cur_info: Info):
    g = cur_info.cur_goal
    if g is None:
        return
    row = next((x for x in cur_info.goals if x['goal-id'] == g._id), None)
    if row is None:
        return
    if row['memory']:
        cur_info.memory = [MemoryLoader(int(k) if k.isdigit() else k)
                           for k in row['memory']]
        return
    out = call_llm(context(g, ASK, history=log.history(g._id)))
    if out is None:
        return
    mems = _by_names(out)
    log.write('retrieve-memory',
              '<goal-id>%d</goal-id><memory-ids>%s</memory-ids>'
              % (g._id, ''.join('<id>%d</id>' % m._id for m in mems)), g._id)
    row['memory'] = [str(m._id) for m in mems]
    cur_info.memory = mems
