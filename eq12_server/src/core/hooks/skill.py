"""[skill] 给当前 goal 选技能 → 没有就造（SKILL CREATOR）→ 按技能执行。

进度看日志：没选过 → 选；选了说没有 → 造；有了 → 执行。
- 子目标类：按「子目标格式」出子 goal
- 原子动作类：按「原子动作格式」投队列，置 action 结束这一轮
提示词都用 llm_client.context()，只有最后一句「现在要做」不同。
"""
import base64
import os
import re
import xml.etree.ElementTree as ET

from ..log import log, read
from .goal import chosen_skill, finish, history, make_goal, model_failed
from .tools.checker import check
from .tools.llm_client import call_llm, context, skills
from .tools.loader import HOOKS_DIR, GoalLoader, SkillLoader

MAX_DEPTH = 4          # 最多拆几层
MAX_ERRORS = 3         # 模型输出坏几次就放弃这个 goal
EQ12_DIR = os.path.abspath(os.path.join(HOOKS_DIR, '..', '..', '..'))

ASK_PICK = '从「我现有的技能」里选一个来完成「当前目标」。只回答编号；都不合适回答 0。'
ASK_CREATE = ('「我现有的技能」里没有合适的。照元技能「造技能」，为完成「当前目标」写一个新技能。'
              '只输出一个 <skill>，不解释、不加 ``` 围栏。')
ASK_SPLIT = ('用「所用技能」完成「当前目标」：照「子目标格式」拆出下一层子目标。'
             '只输出 <sub_goals>，不解释、不加 ``` 围栏。')
ASK_ACT = ('用「所用技能」推进「当前目标」：照「原子动作格式」写出这一步要做的动作。'
           '只输出 <atom_actions>，不解释、不加 ``` 围栏。')


def _extract(reply, tag):
    m = re.search(r'<%s>.*</%s>' % (tag, tag), reply or '', re.S)
    return m.group(0) if m else None


def _skill_key(s):
    """技能在 SkillLoader 里的名字：编号文件用数字，seed 里的用名字。"""
    return int(s.id) if (s.id or '').isdigit() else s.name


# ---------- 选 / 造 ----------

def _pick(self, g):
    gid = int(g.id)
    listed = skills()
    if not listed:
        log('skill', 'skill.none', {'goal': gid}, '还没有技能')
        return
    reply = call_llm(context(g, ASK_PICK, history=history(gid)), max_tokens=8)
    if reply is None:
        model_failed(self.user_info)
        return
    m = re.search(r'\d+', reply)
    n = int(m.group(0)) if m else 0
    if 1 <= n <= len(listed):
        s = listed[n - 1]
        log('skill', 'skill.pick', {'goal': gid, 'skill': _skill_key(s)}, s.name)
    else:
        log('skill', 'skill.none', {'goal': gid}, '没有合适的技能')


def _create(self, g):
    gid = int(g.id)
    reply = call_llm(context(g, ASK_CREATE, history=history(gid)))
    if reply is None:
        model_failed(self.user_info)
        return
    text = _extract(reply, 'skill')
    why = check(text, 'skill') if text else '没有 <skill>'
    if why:
        log('error', 'skill.create', {'goal': gid}, why)
        return
    s = SkillLoader.new(text)
    log('skill', 'skill.create', {'goal': gid, 'skill': int(s.id)}, s.name)


# ---------- 执行 ----------

def _payload(a):
    """<atom_action> → (队列名, 载荷)，载荷格式见 core/queues.md。"""
    q = (a.findtext('queue') or '').strip()
    text = (a.findtext('text') or '').strip()
    if q in ('tts', 'pub/leg', 'pub/face'):
        return q, text
    if q == 'pub/eye':
        return q, text.encode()
    if q == '_pub/delay':
        return q, {'text': text, 'in': float(a.findtext('in'))}
    if q == '_pub/feishu':
        img = (a.findtext('img') or '').strip()
        if not img:
            return q, {'text': text}
        with open(os.path.join(EQ12_DIR, img), 'rb') as f:      # 绝对路径时 join 原样返回
            return q, {'img': base64.b64encode(f.read()).decode()}
    if q == '_pub/desktop':
        cmd = {k: a.findtext(k).strip() for k in ('type', 'value', 'direction', 'time')
               if a.findtext(k) is not None}
        if cmd.get('type') in ('mouse', 'scroll'):
            cmd['value'] = int(cmd['value'])
        if 'time' in cmd:
            cmd['time'] = float(cmd['time'])
        return q, cmd
    raise ValueError('不认识的队列 %r' % q)


def _split(g, root):
    gid = int(g.id)
    subs = list(root.iter('sub_goal'))
    if not subs:
        log('error', 'skill', {'goal': gid}, '<sub_goals> 是空的')
    for x in subs:
        child = GoalLoader.new(make_goal(x.findtext('name') or '', x.findtext('content') or '', father=gid))
        g.add_child(int(child.id))
        log('split', 'skill', {'goal': gid, 'child': int(child.id)}, child.content)


def _act(self, g, root):
    gid = int(g.id)
    sent = []
    for a in root.iter('atom_action'):
        try:
            q, payload = _payload(a)
        except (OSError, TypeError, ValueError, AttributeError) as e:
            log('error', 'skill', {'goal': gid}, '动作没投出去：%s' % e)
            continue
        self.queues[q].put(payload)
        shown = '<图片>' if isinstance(payload, dict) and 'img' in payload else payload
        print('[brain] skill → %s: %s' % (q, shown), flush=True)
        log('act', q, {'goal': gid}, '%s %s' % (q, shown))
        sent.append(q)
    if sent:
        self.user_info['action'] = sent


def _run(self, g, s):
    gid = int(g.id)
    is_split = s.type == '子目标'
    depth, node = 0, g
    while node.father is not None:
        depth, node = depth + 1, GoalLoader(node.father)
    if is_split and depth >= MAX_DEPTH:
        finish(g, '拆得太深了，放弃')
        return
    tag, ask = ('sub_goals', ASK_SPLIT) if is_split else ('atom_actions', ASK_ACT)
    reply = call_llm(context(g, ask, s, history(gid)))
    if reply is None:
        model_failed(self.user_info)
        return
    try:
        root = ET.fromstring(_extract(reply, tag))
    except (TypeError, ET.ParseError) as e:
        log('error', 'skill', {'goal': gid}, '输出不是合法的 <%s>：%s' % (tag, e))
        return
    _split(g, root) if is_split else _act(self, g, root)


def hook(self):
    ui = self.user_info
    g = ui.get('goal')
    if g is None or ui.get('action'):
        return
    gid = int(g.id)
    rows = read(gid)
    if sum(r['kind'] == 'error' for r in rows) >= MAX_ERRORS:
        finish(g, '模型输出坏了 %d 次，放弃' % MAX_ERRORS)
        ui['goal'] = None
        return

    s = chosen_skill(gid)
    if s is not None:
        _run(self, g, s)
    elif any(r['who'] == 'skill.none' for r in rows):
        _create(self, g)
    else:
        _pick(self, g)
