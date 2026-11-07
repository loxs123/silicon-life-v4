import json
import queue
import time

from ...config import (QUEUE_ASR, QUEUE_DELAY_SUB, QUEUE_DESKTOP_SUB,
                       QUEUE_EYE_SUB, QUEUE_FEISHU_SUB, QUEUE_LEG_SUB)
from ..info import Info
from .tools import log

TOPICS = (QUEUE_ASR, QUEUE_FEISHU_SUB, QUEUE_DELAY_SUB, QUEUE_DESKTOP_SUB,
          QUEUE_LEG_SUB, QUEUE_EYE_SUB)

def _fetch(q):
    items = []
    while True:
        try:
            items.append(q.get_nowait())
        except queue.Empty:
            return items


def hook(cur_info: Info):
    if not cur_info.loaded:
        goals, cur_goal, cur_skill, cur_memories, context = log.read()
        cur_info.goals = goals
        cur_info.cur_goal = cur_goal
        cur_info.cur_skill = cur_skill
        cur_info.cur_memories = cur_memories
        cur_info.context = context

    cur_info.cur_messages = []
    for name in TOPICS:
        q = cur_info.queues[name]
        for msg in _fetch(q):
            log.write('queue-msg', msg, cur_info.cur_goal)
            cur_info.cur_messages.append(msg)
        
    
