"""当天日志 hooks/logs/YYYY-MM-DD.log：一行一个 JSON，只追加（格式见 core/log.md §4）。

    log('act', 'tts', {'goal': 3}, '你好呀')
    read(3)    # goal 3 的所有行
"""
import json
import os
import threading
import time

LOGS = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'hooks', 'logs')
CUT = 300              # out 最多几个字
_LOCK = threading.Lock()


def _path():
    return os.path.join(LOGS, time.strftime('%Y-%m-%d') + '.log')


def log(kind, who, arg=None, out=None):
    row = {'t': time.strftime('%H:%M:%S'), 'kind': kind, 'who': who}
    if arg is not None:
        row['arg'] = arg
    if out is not None:
        out = out if isinstance(out, str) else json.dumps(out, ensure_ascii=False)
        row['out'] = out if len(out) <= CUT else out[:CUT] + '…(+%d)' % (len(out) - CUT)
    with _LOCK:
        os.makedirs(LOGS, exist_ok=True)
        with open(_path(), 'a', encoding='utf-8') as f:
            f.write(json.dumps(row, ensure_ascii=False) + '\n')
    print('[log] %s %s %s %s' % (row['t'], kind, who, row.get('out', '')), flush=True)


def read(goal=None):
    if not os.path.exists(_path()):
        return []
    with open(_path(), encoding='utf-8') as f:
        rows = [json.loads(line) for line in f if line.strip()]
    return rows if goal is None else [r for r in rows if r.get('arg', {}).get('goal') == goal]
