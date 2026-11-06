import json
import os
import time

LOGS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'logs')
CUT = 200
_DAY = ''
_ROWS = []


def _rows():
    global _DAY, _ROWS
    day = time.strftime('%Y-%m-%d')
    if day != _DAY:
        path = os.path.join(LOGS, day + '.log')
        _ROWS = []
        if os.path.exists(path):
            with open(path, encoding='utf-8') as f:
                _ROWS = [json.loads(line) for line in f if line.strip()]
        _DAY = day
    return _ROWS


def write(kind, content='', goal=None):
    if not isinstance(content, str):
        content = json.dumps(content, ensure_ascii=False)
    row = {'type': kind, 'content': content,
           'time': time.strftime('%Y-%m-%d %H:%M:%S')}
    if goal is not None:
        row['goal'] = goal
    os.makedirs(LOGS, exist_ok=True)
    with open(os.path.join(LOGS, time.strftime('%Y-%m-%d') + '.log'), 'a',
              encoding='utf-8') as f:
        f.write(json.dumps(row, ensure_ascii=False) + '\n')
    _rows().append(row)
    print('[log] %s %s %s' % (kind, goal or '', content[:CUT]), flush=True)


def read(goal=None, kind=None):
    rows = _rows()
    if goal is not None:
        rows = [r for r in rows if r.get('goal') == goal]
    if kind is not None:
        rows = [r for r in rows if r.get('type') == kind]
    return rows


def last(goal, kind):
    rows = read(goal, kind)
    return rows[-1] if rows else None


def has(goal, kind):
    return last(goal, kind) is not None


def history(goal, n=20):
    rows = read(goal)[-n:]
    lines = ['%s %s：%s' % (r['time'][11:], r['type'], r['content'][:CUT]) for r in rows]
    return '\n'.join(lines) or '（还没开始）'
