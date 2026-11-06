import json
import os
import time

LOGS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'logs')

def write(kind, content=None, goal=None):
    row = {'type': kind, 'content': content, 'goal': goal,
           'time': time.strftime('%Y-%m-%d %H:%M:%S')}
    
    with open(os.path.join(LOGS, time.strftime('%Y-%m-%d') + '.log'), 'a',
              encoding='utf-8') as f:
        f.write(json.dumps(row, ensure_ascii=False) + '\n')
    
    # print('[log] %s %s %s' % (kind, goal if goal is not None else '', shown[:CUT]),
    #       flush=True)

def read():
    with open(os.path.join(LOGS, time.strftime('%Y-%m-%d') + '.log'), 'a',
              encoding='utf-8') as f:
        ...
