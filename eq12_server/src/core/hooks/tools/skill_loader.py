import os
import re

HOOKS_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SKILLS = os.path.join(HOOKS_DIR, 'skills')

DAY_RE = re.compile(r'^\d{4}-\d{2}-\d{2}$')
NAME_RE = re.compile(r'## name\s*\n(.+)')
MATCH_RE = re.compile(r'## match_function\s*\n```python\n(.*?)\n```', re.S)


def _latest_day():
    days = [n for n in os.listdir(SKILLS)
            if DAY_RE.match(n) and os.path.isdir(os.path.join(SKILLS, n))]
    return os.path.join(SKILLS, max(days)) if days else None


def _find(name):
    for base in (_latest_day(), os.path.join(SKILLS, 'seed')):
        if base:
            path = os.path.join(base, name + '.md')
            if os.path.exists(path):
                return path
    raise FileNotFoundError('没有这个技能: %s' % name)


def load(name):
    path = _find(name)
    with open(path, encoding='utf-8') as f:
        text = f.read()
    namespace = {'os': os, 're': re}
    exec(MATCH_RE.search(text).group(1), namespace)
    return {'path': path,
            'name': NAME_RE.search(text).group(1).strip(),
            'match': namespace['match'],
            'content': text.split('## content', 1)[1].strip()}


def load_all():
    base = _latest_day() or os.path.join(SKILLS, 'seed')
    names = sorted(n[:-3] for n in os.listdir(base) if n.endswith('.md'))
    return [load(name) for name in names]
