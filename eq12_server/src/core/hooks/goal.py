import time

from ...config import QUEUE_ASR, QUEUE_DELAY_SUB, QUEUE_FEISHU_SUB
from ..info import Info
from .tools import log
from .tools.loader import GoalLoader

PLAN_ROOT = '今天还没有计划'
MSG_QUEUES = (QUEUE_ASR, QUEUE_FEISHU_SUB, QUEUE_DELAY_SUB)


def _add(cur_info, name, content, father=None, message=False):
    g = GoalLoader.new({'name': name, 'content': content, 'child-goals': [],
                        'father-goal-id': father, 'finish-time': '',
                        'create-time': time.strftime('%Y-%m-%d %H:%M:%S')})
    log.write('create-goal', g.data, g._id)
    cur_info.goals.append({'goal-id': g._id, 'goal-name': name, 'father': father,
                           'finish': False, 'message': message, 'skill': '',
                           'memory': None})
    return g


def _leaf(tree, gid):
    goal = next((x for x in tree if x['goal-id'] == gid), None)
    if goal is None or goal['finish']:
        return None
    kids = [x for x in tree if x['father'] == gid]
    if not kids:
        return gid
    for kid in kids:
        got = _leaf(tree, kid['goal-id'])
        if got is not None:
            return got
    return None


def _pick(tree):
    for goal in sorted(tree, key=lambda x: (0 if x['message'] else 1, x['goal-id'])):
        gid = _leaf(tree, goal['goal-id'])
        if gid is not None:
            return GoalLoader(gid)
    return None


def hook(cur_info: Info):
    for msg in cur_info.context:
        if msg.get('queue') in MSG_QUEUES and msg.get('text'):
            said = msg['text']
            g = _add(cur_info, said[:10], said, message=True)
            log.write('receive-message', {'id': g._id}, g._id)
    cur_info.context.clear()

    if not cur_info.goals:
        _add(cur_info, PLAN_ROOT, PLAN_ROOT)

    for row in cur_info.goals:
        kids = [x for x in cur_info.goals if x['father'] == row['goal-id']]
        if row['finish'] or not kids or not all(k['finish'] for k in kids):
            continue
        g = GoalLoader(row['goal-id'])
        g.finish()
        row['finish'] = True
        log.write('finish-goal', {}, g._id)

    cur_info.cur_goal = _pick(cur_info.goals)
    if cur_info.cur_goal is not None and not log.has(cur_info.cur_goal._id, 'start-goal'):
        log.write('start-goal', {}, cur_info.cur_goal._id)
