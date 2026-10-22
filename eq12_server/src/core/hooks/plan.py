import json
import os
import re
import time

from .tools import skill_loader
from .tools.llm_client import call_llm

HOOKS_DIR = os.path.dirname(os.path.abspath(__file__))
DAY_FMT = '%Y-%m-%d'
PLAN_FILE = 'goal.json'
PLAN_GOAL = '今天还没有计划'
PLAN_MAX_TOKENS = 1024
PLAN_THINKING_BUDGET = 1024

TIME_RE = re.compile(r'^\d{1,2}:\d{2}-\d{1,2}:\d{2}\s')


def hook(self):
    date = time.strftime(DAY_FMT)
    path = os.path.join(HOOKS_DIR, 'states', date, PLAN_FILE)
    if os.path.exists(path):
        return

    skill = skill_loader.load('plan')
    if not skill['match'](PLAN_GOAL):
        return
    prompt = skill['content']

    self_md = os.path.join(HOOKS_DIR, 'memory',
                           time.strftime(DAY_FMT, time.localtime(time.time() - 86400)),
                           'self.md')
    if not os.path.exists(self_md):
        self_md = os.path.join(HOOKS_DIR, 'memory', 'seed', 'self.md')
    with open(self_md, encoding='utf-8') as f:
        persona = f.read().strip()

    text = call_llm([{'role': 'system', 'content': persona},
                     {'role': 'user', 'content': prompt.format(date=date)}],
                    max_tokens=PLAN_MAX_TOKENS,
                    thinking_budget=PLAN_THINKING_BUDGET)

    text = text.strip()
    if text.startswith('```'):
        text = '\n'.join(ln for ln in text.splitlines()
                         if not ln.lstrip().startswith('```'))
    targets = [{'content': t['content'].strip(), 'parent': None}
               for t in json.loads(text)['target_list']
               if TIME_RE.match(t['content'].strip())]

    plan_dict = {'target_list': targets, 'cur_target': 0}
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(plan_dict, f, ensure_ascii=False, indent=2)

    self.user_info['plan'] = plan_dict
    self.user_info['plan_path'] = path
    print('[brain] plan -> %s' % os.path.relpath(path, HOOKS_DIR), flush=True)

if __name__ == '__main__':
    class Test:
        def __init__(self, ):
            self.user_info = {}
    hook(Test())
