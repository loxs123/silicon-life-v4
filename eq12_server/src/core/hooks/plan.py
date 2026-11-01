"""[plan] 今天还没有 goal → 建根目标 goal_0001「今天还没有计划」，指定用 plan 技能拆它。

不调模型：排计划是 skill hook 按 skills/seed/plan.xml 去拆。
"""
from ..log import log
from .goal import make_goal
from .tools.loader import GoalLoader

PLAN_GOAL = '今天还没有计划'
PLAN_SKILL = 'plan'


def hook(self):
    if GoalLoader.ids():
        return
    g = GoalLoader.new(make_goal('今天', PLAN_GOAL))
    log('goal', 'plan', {'goal': int(g.id)}, PLAN_GOAL)
    log('skill', 'plan', {'goal': int(g.id), 'skill': PLAN_SKILL}, PLAN_SKILL)
