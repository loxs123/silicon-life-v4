from ..info import Info
from .tools import log
from .tools.checker import check
from .tools.llm_client import call_llm, context
from .tools.loader import GoalLoader, MemoryLoader, read_json

ASK = ('用 memory_creator 这个元技能，把刚做完的这个目标写成一条记忆：'
       '只输出一个 JSON 对象（格式见 memory.json），不解释、不要围栏。')


def hook(cur_info: Info):
    for g in GoalLoader.all():
        if not g.finish_time or log.has(g._id, 'create-memory'):
            continue
        data = read_json(call_llm(context(g, ASK, history=log.history(g._id))))
        bad = check(data, 'memory')
        if bad:
            print('[memory_creator] 记忆不合规: %s' % bad, flush=True)
            return
        m = MemoryLoader.new(data)
        log.write('create-memory', m.data, g._id)
        return
