"""skill_loader 冒烟测试：不联网，用临时技能目录。

跑法（在 eq12_server/ 目录下）：
    python tests/test_skill_loader.py

覆盖：
  1. 最近日期目录里没有这个技能 → 从 seed 读
  2. 最近日期目录里有 → 优先用最近那天的（不看更早的）
  3. load_all：收最近日期目录里的技能
  4. 仓库里真实的 plan 技能：match 认「今天还没有计划」
"""
import os
import shutil
import sys
import tempfile
import types

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

# 本机可能没装 dashscope：先塞一个假的进 sys.modules，hooks/__init__.py 才能 import 过去
_fake = types.ModuleType('dashscope')
_fake.api_key = ''
_fake.Generation = types.SimpleNamespace()
sys.modules['dashscope'] = _fake

from src.core.hooks.tools import skill_loader  # noqa: E402

_ORIG_SKILLS = skill_loader.SKILLS

SKILL = '''## name
{name}

## match_function
```python
def match(goal):
    return '提醒' in goal
```

## content
{content}
'''


def _write(path, name, content):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        f.write(SKILL.format(name=name, content=content))


def test_seed_fallback():
    d = tempfile.mkdtemp(prefix='skill_test_')
    try:
        skill_loader.SKILLS = d
        _write(os.path.join(d, 'seed', 'reminder.md'), 'reminder', '帮我记着')
        s = skill_loader.load('reminder')
        assert s['name'] == 'reminder', s
        assert s['path'] == os.path.join(d, 'seed', 'reminder.md'), s
        assert s['match']('提醒我喝水') is True
        assert s['match']('今天天气') is False
        assert s['content'] == '帮我记着', s
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_latest_day_wins():
    d = tempfile.mkdtemp(prefix='skill_test_')
    try:
        skill_loader.SKILLS = d
        _write(os.path.join(d, 'seed', 'reminder.md'), 'reminder', 'seed 的')
        _write(os.path.join(d, '2026-01-01', 'reminder.md'), 'reminder', '1 号的')
        _write(os.path.join(d, '2026-02-02', 'reminder.md'), 'reminder', '2 号的')
        assert skill_loader.load('reminder')['content'] == '2 号的'
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_latest_day_missing_skill_uses_seed():
    d = tempfile.mkdtemp(prefix='skill_test_')
    try:
        skill_loader.SKILLS = d
        _write(os.path.join(d, 'seed', 'reminder.md'), 'reminder', 'seed 的')
        _write(os.path.join(d, '2026-02-02', 'other.md'), 'other', '别的技能')
        assert skill_loader.load('reminder')['content'] == 'seed 的'
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_load_all():
    d = tempfile.mkdtemp(prefix='skill_test_')
    try:
        skill_loader.SKILLS = d
        _write(os.path.join(d, 'seed', 'reminder.md'), 'reminder', 'seed 的')
        _write(os.path.join(d, '2026-02-02', 'a.md'), 'a', 'A')
        _write(os.path.join(d, '2026-02-02', 'b.md'), 'b', 'B')
        assert [s['name'] for s in skill_loader.load_all()] == ['a', 'b']
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_real_skill():
    s = skill_loader.load('plan')
    assert s['name'] == 'plan', s
    assert s['match']('今天还没有计划') is True
    assert s['match']('别的目标') is False
    assert s['content'].startswith('今天是 {date}。'), s['content'][:20]


def main():
    skill_loader.SKILLS = _ORIG_SKILLS
    try:
        test_seed_fallback()
        test_latest_day_wins()
        test_latest_day_missing_skill_uses_seed()
        test_load_all()
        skill_loader.SKILLS = _ORIG_SKILLS
        test_real_skill()
    finally:
        skill_loader.SKILLS = _ORIG_SKILLS
    print('SKILL LOADER TEST PASS: seed / 最近日期优先 / 缺技能回 seed / load_all / 真实技能 全通过')


if __name__ == '__main__':
    main()
