import base64
import os
import time
import xml.etree.ElementTree as ET
from xml.sax.saxutils import escape

from ...config import (QUEUE_DELAY_PUB, QUEUE_DESKTOP_PUB, QUEUE_EYE_PUB,
                       QUEUE_FACE_PUB, QUEUE_FEISHU_PUB, QUEUE_LEG_PUB, QUEUE_TTS)
from ..info import Info
from .tools import log
from .tools.checker import check
from .tools.llm_client import call_llm, context, xml
from .tools.loader import GoalLoader

SUB = '照当前技能把当前目标拆成下一层子目标：只输出一个 <sub_goals>，不解释。'
ACT = '照当前技能给出这一步要做的原子动作：只输出一个 <atom_actions>，不解释。'
TEXT_QUEUES = (QUEUE_TTS, QUEUE_LEG_PUB, QUEUE_FACE_PUB)


def _b64(path):
    if os.path.isfile(path):
        with open(path, 'rb') as f:
            return base64.b64encode(f.read()).decode('ascii')
    return path


def _payload(node):
    q = node.findtext('queue')
    text = node.findtext('text')
    if q in TEXT_QUEUES:
        return text or None
    if q == QUEUE_EYE_PUB:
        return b'photo'
    if q == QUEUE_DESKTOP_PUB:
        data = {k: node.findtext(k)
                for k in ('type', 'value', 'direction', 'time') if node.findtext(k)}
        return data or None
    if q == QUEUE_FEISHU_PUB:
        img = node.findtext('img')
        if img:
            return {'img': _b64(img)}
        return {'text': text} if text else None
    if q == QUEUE_DELAY_PUB:
        sec = node.findtext('in')
        return {'text': text, 'in': float(sec)} if text and sec else None
    return None


def _child(cur_info, g, node):
    child = GoalLoader.new(
        '<goal><id/><name>%s</name><content>%s</content><child-goals/>'
        '<father-goal-id>%d</father-goal-id><create-time>%s</create-time>'
        '<finish-time/></goal>'
        % (escape(node.findtext('name') or g.name or ''),
           escape(node.findtext('content') or ''), g._id,
           time.strftime('%Y-%m-%d %H:%M:%S')))
    g.add_child(child._id)
    log.write('create-goal', child.raw, child._id)
    cur_info.goals.append({'goal-id': child._id,
                           'goal-name': node.findtext('name') or g.name,
                           'father': g._id, 'finish': False, 'message': False,
                           'skill': '', 'memory': []})
    return child


def hook(cur_info: Info):
    g, sk = cur_info.cur_goal, cur_info.cur_skill
    if g is None or sk is None or log.has(g._id, 'atom-action'):
        return
    ask = SUB if sk.type == '子目标' else ACT
    text = xml(call_llm(context(g, ask, skill=sk, history=log.history(g._id))))
    if not text:
        return
    if sk.type == '子目标':
        bad = check(text, 'sub_goals')
        if bad:
            print('[action] 子目标不合规: %s' % bad, flush=True)
            return
        for node in ET.fromstring(text):
            _child(cur_info, g, node)
        cur_info.output = text
        return
    bad = check(text, 'atom_actions')
    if bad:
        print('[action] 原子动作不合规: %s' % bad, flush=True)
        return
    sent = []
    for node in ET.fromstring(text):
        name = node.findtext('queue')
        payload = _payload(node)
        q = cur_info.queues.get(name)
        if q is None or payload is None:
            print('[action] 投不出去 %s' % name, flush=True)
            continue
        q.put(payload)
        print('[brain] action → %s: %s' % (name, str(payload)[:60]), flush=True)
        sent.append(name)
    log.write('atom-action', text, g._id)
    cur_info.action = sent
    cur_info.output = text
