"""[memory] 任务级 goal 完成后，照元技能「写记忆」写一条记忆。

任务级 = 外来消息的根 goal，或计划（goal 1）下的一段。
哪些还没写：日志里有 finish、没有 memory。
提示词用 llm_client.context()，「经过」换成这个 goal 整棵子树的日志。
"""
import re

from ..log import log, read
from .goal import chosen_skill, model_failed
from .tools.checker import check
from .tools.llm_client import call_llm, context
from .tools.loader import GoalLoader, MemoryLoader

HISTORY_N = 30         # 子树日志最多给几行
ASK_MEMORY = ('「当前目标」刚完成。照元技能「写记忆」，把这次值得记的写成一条记忆，time 用当前目标的 finish-time。'
              '只输出一个 <memory>，不解释、不加 ``` 围栏；真的没有值得记的，只输出 <none/>。')


def _subtree(gid):
    ids = [gid]
    for c in GoalLoader(gid).children:
        ids += _subtree(c)
    return ids


def _next_pending():
    rows = read()
    written = {r['arg']['goal'] for r in rows if r['kind'] == 'memory'}
    for r in rows:
        if r['kind'] != 'finish':
            continue
        gid = r['arg']['goal']
        if gid != 1 and gid not in written and GoalLoader(gid).father in (None, 1):
            return gid
    return None


def hook(self):
    if self.user_info.get('action'):
        return
    gid = _next_pending()
    if gid is None:
        return

    ids = set(_subtree(gid))
    rows = [r for r in read() if r.get('arg', {}).get('goal') in ids][-HISTORY_N:]
    history = '\n'.join('%s %s %s' % (r['t'], r['kind'], r.get('out', '')) for r in rows)
    reply = call_llm(context(GoalLoader(gid), ASK_MEMORY, chosen_skill(gid), history))
    if reply is None:
        model_failed(self.user_info)
        return

    m = re.search(r'<memory>.*</memory>', reply, re.S)
    why = check(m.group(0), 'memory') if m else '没什么值得记的'
    if why:
        log('memory', 'memory', {'goal': gid}, '不记：%s' % why)
    else:
        mem = MemoryLoader.new(m.group(0))
        log('memory', 'memory', {'goal': gid, 'memory': int(mem.id)}, mem.name)
