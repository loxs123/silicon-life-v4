import json
import os
import time

LOGS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'logs')
FIRST_GOAL_NAME = '创建今日计划'
FIRST_GOAL_CONTENT = '制定今日行动计划，确定今天要完成的几件事情'

def write(kind, content=None, goal=None):
    row = {'type': kind, 'content': content, 'goal': goal,
           'time': time.strftime('%Y-%m-%d %H:%M:%S')}
    
    with open(os.path.join(LOGS, time.strftime('%Y-%m-%d') + '.log'), 'a',
              encoding='utf-8') as f:
        f.write(json.dumps(row, ensure_ascii=False) + '\n')
    
    # print('[log] %s %s %s' % (kind, goal if goal is not None else '', shown[:CUT]),
    #       flush=True)

def read():
    # 每天 至少有一条日志 是今天做什么 什么规划

    # 这里加上
    log_file = os.path.join(LOGS, time.strftime('%Y-%m-%d') + '.log')

    if not os.path.exists(log_file):
        first_goal = {
            "type": "create-goal",
            "content":{
                "id": 1,
                "name": FIRST_GOAL_NAME,
                "content": FIRST_GOAL_CONTENT,
                "child-goals": [],
                "father-goal-id": -1,
            },
            "time": time.strftime('%Y-%m-%d %H:%M:%S'), 
            "goal": 1
        }
        
        with open(log_file, 'w') as f:
            f.write(json.dumps(first_goal, ensure_ascii=False) + '\n')
    
    goals = []
    cur_memories = []
    cur_goal = None
    cur_skill = None
    context = []
    with open(os.path.join(LOGS, time.strftime('%Y-%m-%d') + '.log'), 
              encoding='utf-8') as f:
        for line in f:
            event = json.loads(line.strip())
            if event['type'] == 'create-goal':
                cur_memories.clear()
                cur_goal = None
                cur_skill = None
                context = []

                goals.append(event['content'])
                cur_goal = event['content']
                
            if event['type'] == 'retrieve-memory':
                cur_memories = event['content']["memory-ids"]
            
            if event['type'] == 'retrieve-skill':
                cur_skill = event['content']['skill-id']
            
            if event['type'] == 'queue-msg':
                context.append(event['content'])
            
            if event['type'] == 'atom-action':
                context.append(event['content'])
            
            if event['type'] == 'check-goal':
                context.append(event['content'])

    return goals, cur_goal, cur_skill, cur_memories, context
