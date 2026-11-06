from ..info import Info
from .tools import log
from .tools.llm_client import call_llm, context

ASK = '当前目标做到了吗？只回一个字：是 或 否。'


def hook(cur_info: Info):
    g = cur_info.cur_goal
    if g is None or g.finish_time or g.children:
        return
    if not log.has(g._id, 'atom-action') or log.has(g._id, 'check-goal'):
        return
    out = call_llm(context(g, ASK, history=log.history(g._id)))
    if out is None:
        return
    done = '是' in out and '否' not in out
    log.write('check-goal',
              '<goal><goal-id>%d</goal-id><done>%d</done></goal>' % (g._id, int(done)),
              g._id)
    if done:
        g.finish()
        row = next((x for x in cur_info.goals if x['goal-id'] == g._id), None)
        if row is not None:
            row['finish'] = True
        log.write('finish-goal', '<goal-id>%d</goal-id>' % g._id, g._id)
