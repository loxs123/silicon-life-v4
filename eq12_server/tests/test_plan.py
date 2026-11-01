"""plan hook 冒烟测试：不联网、不调模型，用临时 hooks 目录。

跑法（在 eq12_server/ 目录下）：
    python tests/test_plan.py

覆盖：
  1. 今天还没有 goal → 按 protocols/goal.xml 建 goal_0001「今天还没有计划」，日志里指定用 plan 技能
  2. 今天已经有 goal → 什么都不做
  3. seed 里的 plan 技能符合 protocols/skill.xml，类型是「子目标」
"""
import importlib
import os
import shutil
import sys
import tempfile
import types

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

_fake = types.ModuleType('dashscope')
_fake.api_key = ''
_fake.Generation = types.SimpleNamespace()
sys.modules['dashscope'] = _fake

loader = importlib.import_module('src.core.hooks.tools.loader')
logmod = importlib.import_module('src.core.log')
plan = importlib.import_module('src.core.hooks.plan')
from src.core.hooks.tools.checker import check  # noqa: E402


class Harness:
    def __init__(self):
        self.dir = tempfile.mkdtemp(prefix='plan_test_')
        shutil.copytree(os.path.join(loader.HOOKS_DIR, 'skills', 'seed'),
                        os.path.join(self.dir, 'skills', 'seed'))
        self.orig = (loader.HOOKS_DIR, logmod.LOGS)
        loader.HOOKS_DIR = self.dir
        logmod.LOGS = os.path.join(self.dir, 'logs')
        self.self = types.SimpleNamespace(user_info={}, queues={})

    def close(self):
        loader.HOOKS_DIR, logmod.LOGS = self.orig
        shutil.rmtree(self.dir, ignore_errors=True)


def test_create_root():
    h = Harness()
    try:
        plan.hook(h.self)
        assert loader.GoalLoader.ids() == [1]
        g = loader.GoalLoader(1)
        assert check(g.text, 'goal') == '', g.text
        assert g.content == plan.PLAN_GOAL and g.father is None and not g.finish_time
        picks = [r['arg']['skill'] for r in logmod.read(1) if r['kind'] == 'skill']
        assert picks == [plan.PLAN_SKILL], picks
    finally:
        h.close()


def test_exists_noop():
    h = Harness()
    try:
        plan.hook(h.self)
        plan.hook(h.self)
        assert loader.GoalLoader.ids() == [1]
    finally:
        h.close()


def test_plan_skill():
    s = loader.SkillLoader(plan.PLAN_SKILL)
    assert check(s.text, 'skill') == '', check(s.text, 'skill')
    assert s.type == '子目标' and s.name == 'plan'


def main():
    test_create_root()
    test_exists_noop()
    test_plan_skill()
    print('PLAN TEST PASS: 建根目标 / 已有不动 / plan 技能符合协议 全通过')


if __name__ == '__main__':
    main()
