import re

from ..info import Info
from .tools import log
from .tools.checker import check
from .tools.llm_client import call_llm, context, skills, xml
from .tools.loader import SkillLoader

ASK = '从「我现有的技能」里挑一个最适合做当前目标的：只回编号，回 0 表示一个都不合适。'
CREATE = '用 skill_creator 这个元技能，把当前目标要做的事写成一个新技能：只输出一个 <skill>，不解释。'


def _choose(out, g):
    nums = re.findall(r'\d+', out)
    pick = int(nums[0]) if nums else 0
    pool = skills()
    if 0 < pick <= len(pool):
        return pool[pick - 1]
    text = xml(call_llm(context(g, CREATE, history=log.history(g._id))))
    if not text:
        return None
    bad = check(text, 'skill')
    if bad:
        print('[skill] 技能不合规: %s' % bad, flush=True)
        return None
    sk = SkillLoader.new(text)
    log.write('create-skill', sk.raw, g._id)
    return sk


def hook(cur_info: Info):
    g = cur_info.cur_goal
    if g is None:
        return
    row = next((x for x in cur_info.goals if x['goal-id'] == g._id), None)
    if row is None:
        return
    if row['skill']:
        cur_info.cur_skill = SkillLoader(int(row['skill']) if row['skill'].isdigit()
                                         else row['skill'])
        return
    out = call_llm(context(g, ASK, history=log.history(g._id)))
    if out is None:
        return
    sk = _choose(out, g)
    if sk is None:
        return
    log.write('retrieve-skill',
              '<goal-id>%d</goal-id><skill-ids><id>%s</id></skill-ids>'
              % (g._id, sk._id), g._id)
    row['skill'] = str(sk._id)
    cur_info.cur_skill = sk
