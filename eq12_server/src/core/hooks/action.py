import base64
import os
import time

from ...config import (QUEUE_DELAY_PUB, QUEUE_DESKTOP_PUB, QUEUE_EYE_PUB,
                       QUEUE_FACE_PUB, QUEUE_FEISHU_PUB, QUEUE_LEG_PUB, QUEUE_TTS)
from ..info import Info
from .tools import log
from .tools.checker import check
from .tools.llm_client import call_llm, context
from .tools.loader import GoalLoader, read_json

SUB = ('照当前技能把当前目标拆成下一层子目标：只输出一个 JSON 对象 '
       '{"sub_goals": [...]}（格式见 sub_goals.json），不解释。')
ACT = ('照当前技能给出这一步要做的原子动作：只输出一个 JSON 对象 '
       '{"atom_actions": [...]}（格式见 atom_actions.json），不解释。')
TEXT_QUEUES = (QUEUE_TTS, QUEUE_LEG_PUB, QUEUE_FACE_PUB)


def _b64(path):
    if os.path.isfile(path):
        with open(path, 'rb') as f:
            return base64.b64encode(f.read()).decode('ascii')
    return path


def _payload(item):
    q = item.get('queue')
    text = item.get('text')
    if q in TEXT_QUEUES:
        return text or None
    if q == QUEUE_EYE_PUB:
        return b'photo'
    if q == QUEUE_DESKTOP_PUB:
        data = {k: item[k]
                for k in ('type', 'value', 'direction', 'time') if k in item}
        return data or None
    if q == QUEUE_FEISHU_PUB:
        img = item.get('img')
        if img:
            return {'img': _b64(img)}
        return {'text': text} if text else None
    if q == QUEUE_DELAY_PUB:
        return {'text': text, 'in': float(item['in'])} if text and item.get('in') else None
    return None


def _child(cur_info, g, item):
    child = GoalLoader.new({'name': item.get('name') or g.name,
                            'content': item.get('content') or '',
                            'child-goals': [], 'father-goal-id': g._id,
                            'finish-time': '',
                            'create-time': time.strftime('%Y-%m-%d %H:%M:%S')})
    g.add_child(child._id)
    log.write('create-goal', child.data, child._id)
    cur_info.goals.append({'goal-id': child._id,
                           'goal-name': item.get('name') or g.name,
                           'father': g._id, 'finish': False, 'message': False,
                           'skill': '', 'memory': None})
    return child


def hook(cur_info: Info):
    g, sk = cur_info.cur_goal, cur_info.cur_skill
    if g is None or sk is None or log.has(g._id, 'atom-action'):
        return
    ask = SUB if sk.type == '子目标' else ACT
    data = read_json(call_llm(context(g, ask, skill=sk, history=log.history(g._id))))
    kind = 'sub_goals' if sk.type == '子目标' else 'atom_actions'
    bad = check(data, kind)
    if bad:
        print('[action] 不合规: %s' % bad, flush=True)
        return
    if kind == 'sub_goals':
        for item in data['sub_goals']:
            _child(cur_info, g, item)
        cur_info.output = data
        return
    sent = []
    for item in data['atom_actions']:
        name = item.get('queue')
        payload = _payload(item)
        q = cur_info.queues.get(name)
        if q is None or payload is None:
            print('[action] 投不出去 %s' % name, flush=True)
            continue
        q.put(payload)
        print('[brain] action → %s: %s' % (name, str(payload)[:60]), flush=True)
        sent.append(name)
    log.write('atom-action', data, g._id)
    cur_info.action = sent
    cur_info.output = data
