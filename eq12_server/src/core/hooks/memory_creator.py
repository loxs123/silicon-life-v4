from ..info import Info
from .tools import log
from .tools.checker import check
from .tools.llm_client import call_llm, context, xml
from .tools.loader import GoalLoader, MemoryLoader

ASK = '用 memory_creator 这个元技能，把刚做完的这个目标写成一条记忆：只输出一个 <memory>，不解释。'


def hook(cur_info: Info):
    for g in GoalLoader.all():
        if not g.finish_time or log.has(g._id, 'create-memory'):
            continue
        text = xml(call_llm(context(g, ASK, history=log.history(g._id))))
        if not text:
            return
        bad = check(text, 'memory')
        if bad:
            print('[memory_creator] 记忆不合规: %s' % bad, flush=True)
            return
        m = MemoryLoader.new(text)
        log.write('create-memory', m.raw, g._id)
        return
