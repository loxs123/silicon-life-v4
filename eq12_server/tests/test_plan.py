"""plan hook 冒烟测试：不联网、不装 dashscope、不碰真实 hooks 目录（用临时目录）。

跑法（在 eq12_server/ 目录下）：
    python tests/test_plan.py

覆盖：
  1. 今天的 goal.json 不存在 → skill 命中（match 收到固定字符串「今天还没有计划」）
     → 调一次模型 → 落盘（提示词来自 skills/seed/plan.md 的 content）
  2. 今天的 goal.json 已存在 → 不调模型、不覆盖文件
  3. content 不带时间范围的目标被过滤；模型包 ``` 也能解析
  4. cur_target 固定为 0（模型给别的也不采信）
"""
import json
import os
import shutil
import sys
import tempfile
import time
import types

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

# 本机可能没装 dashscope：先塞一个假的进 sys.modules，llm_client 才能 import 过去
_fake = types.ModuleType('dashscope')
_fake.api_key = ''
_fake.Generation = types.SimpleNamespace()
sys.modules['dashscope'] = _fake

import importlib  # noqa: E402

# 不能用 `import src.core.hooks.plan as plan`：hooks/__init__.py 里
# `from .plan import hook` 会把包上的 plan 属性覆盖成函数，那样拿到的是函数不是模块。
plan = importlib.import_module('src.core.hooks.plan')

_ORIG_HOOKS_DIR = plan.HOOKS_DIR
_ORIG_CALL_LLM = plan.call_llm

from src.core.hooks.tools import skill_loader  # noqa: E402
_ORIG_SKILLS = skill_loader.SKILLS

SKILL_MD = '''## name
plan

## match_function
```python
def match(goal):
    return goal == '今天还没有计划'
```

## content
今天是 {date}，给出今天的计划。
'''


class Harness:
    """临时 hooks 目录（含 skill）+ 假 call_llm + 假 self。"""

    reply = None

    def __init__(self):
        self.dir = tempfile.mkdtemp(prefix='plan_test_')
        self.hooks = os.path.join(self.dir, 'hooks')
        os.makedirs(os.path.join(self.hooks, 'memory', 'seed'))
        with open(os.path.join(self.hooks, 'memory', 'seed', 'self.md'), 'w',
                  encoding='utf-8') as f:
            f.write('我是硅基生命。')
        os.makedirs(os.path.join(self.hooks, 'skills', 'seed'))
        with open(os.path.join(self.hooks, 'skills', 'seed', 'plan.md'), 'w',
                  encoding='utf-8') as f:
            f.write(SKILL_MD)
        self.calls = []
        plan.HOOKS_DIR = self.hooks
        plan.call_llm = self._llm
        skill_loader.SKILLS = os.path.join(self.hooks, 'skills')
        self.self = types.SimpleNamespace(user_info={}, queues={})
        self.date = time.strftime(plan.DAY_FMT)
        self.goal = os.path.join(self.hooks, 'states', self.date, plan.PLAN_FILE)

    def _llm(self, messages, **kw):
        self.calls.append((messages, kw))
        return self.reply

    def read_goal(self):
        with open(self.goal, encoding='utf-8') as f:
            return json.load(f)

    def close(self):
        plan.HOOKS_DIR = _ORIG_HOOKS_DIR
        plan.call_llm = _ORIG_CALL_LLM
        skill_loader.SKILLS = _ORIG_SKILLS
        shutil.rmtree(self.dir, ignore_errors=True)


def _plan_json(targets=None, cur=None):
    d = {'target_list': targets if targets is not None else [
        {'content': '09:00-11:00 把 plan.py 写完', 'parent': None},
        {'content': '14:00-16:00 跑通测试', 'parent': None},
    ]}
    if cur is not None:
        d['cur_target'] = cur
    return json.dumps(d, ensure_ascii=False)


def test_skill_matched():
    h = Harness()
    try:
        h.reply = _plan_json()
        plan.hook(h.self)

        assert len(h.calls) == 1, h.calls
        (messages, kw) = h.calls[0]
        assert messages[0] == {'role': 'system', 'content': '我是硅基生命。'}, messages
        assert messages[1]['content'] == \
            '今天是 %s，给出今天的计划。' % h.date, messages[1]
        assert kw['max_tokens'] == plan.PLAN_MAX_TOKENS, kw
        assert kw['thinking_budget'] == plan.PLAN_THINKING_BUDGET, kw

        saved = h.read_goal()
        assert saved == {
            'target_list': [
                {'content': '09:00-11:00 把 plan.py 写完', 'parent': None},
                {'content': '14:00-16:00 跑通测试', 'parent': None},
            ],
            'cur_target': 0,
        }, saved
        assert h.self.user_info['plan'] == saved, h.self.user_info
        assert h.self.user_info['plan_path'] == h.goal, h.self.user_info
    finally:
        h.close()


def test_skill_not_matched_when_goal_exists():
    h = Harness()
    try:
        os.makedirs(os.path.dirname(h.goal))
        with open(h.goal, 'w', encoding='utf-8') as f:
            f.write('{"target_list": [], "cur_target": 0}')

        plan.hook(h.self)

        assert len(h.calls) == 0, '目标文件已存在，skill 不该命中'
        with open(h.goal, encoding='utf-8') as f:
            assert f.read() == '{"target_list": [], "cur_target": 0}'
        assert 'plan' not in h.self.user_info, h.self.user_info
    finally:
        h.close()


def test_bad_content_filtered():
    h = Harness()
    try:
        h.reply = '```json\n' + _plan_json([
            {'content': '09:00-11:00 好的目标', 'parent': None},
            {'content': '没有时间范围', 'parent': None},
        ]) + '\n```'
        plan.hook(h.self)

        assert [t['content'] for t in h.read_goal()['target_list']] == \
            ['09:00-11:00 好的目标'], h.read_goal()
    finally:
        h.close()


def test_cur_target_forced_zero():
    h = Harness()
    try:
        h.reply = _plan_json(cur=5)
        plan.hook(h.self)
        assert h.read_goal()['cur_target'] == 0, h.read_goal()
    finally:
        h.close()


def main():
    test_skill_matched()
    test_skill_not_matched_when_goal_exists()
    test_bad_content_filtered()
    test_cur_target_forced_zero()
    print('PLAN TEST PASS: skill 命中 / 未命中 / 过滤无时间范围 / cur_target 归零 全通过')


if __name__ == '__main__':
    main()
