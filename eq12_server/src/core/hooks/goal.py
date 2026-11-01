"""[goal] 收消息 → 选当前 goal → GOAL CHECKER。

- 收：外来消息各建一个根 goal；动作回执记进日志。只 get_nowait，不等。
- 选：外来消息的根先办，再办今天的计划（goal 1），走到第一个没完成的叶子。
      子 goal 全部完成的父 goal 直接完成。
- 判：做过动作、还没判过 → 问模型「完成了吗」，只答 是 / 否。
"""
import base64
import json
import os
import queue
import time
import xml.etree.ElementTree as ET

from ..log import log, read
from .tools.llm_client import call_llm, context
from .tools.loader import HOOKS_DIR, GoalLoader, SkillLoader, now

MAX_ACTS = 8           # 一个 goal 最多做几次动作
RECEIPT_S = 10         # 等回执最多几秒，期间这个 goal 先不判
RETRY_S = 5            # 模型没回之后几秒内不再调模型
CACHE = os.path.abspath(os.path.join(HOOKS_DIR, '..', '..', '..', 'cache'))

INBOX = ('asr', '_sub/feishu', '_sub/delay')          # 外来消息
RECEIPTS = ('_sub/desktop', 'sub/leg', 'sub/eye')      # 动作回执
HAS_RECEIPT = ('_pub/desktop', 'pub/leg', 'pub/eye')   # 会有回执的动作

ASK_CHECK = '判断「当前目标」完成了没有：标准看「所用技能」的 verify，依据看「经过」。只回答一个字：是 或 否'


# ---------- 给别的 hook 用 ----------

def make_goal(name, content, father=None):
    """按 protocols/goal.xml 拼一个 goal（id 由 GoalLoader.new 填）。"""
    root = ET.Element('goal')
    for tag, text in (('id', ''), ('name', name), ('content', content)):
        ET.SubElement(root, tag).text = text
    ET.SubElement(root, 'child-goals')
    ET.SubElement(root, 'father-goal-id').text = '' if father is None else str(father)
    ET.SubElement(root, 'create-time').text = now()
    ET.SubElement(root, 'finish-time').text = ''
    return ET.tostring(root, encoding='unicode')


def history(gid, n=15):
    """日志里这个 goal 的最近几行。"""
    rows = read(gid)[-n:]
    return '\n'.join('%s %s %s' % (r['t'], r['kind'], r.get('out', '')) for r in rows) or '（还没开始）'


def chosen_skill(gid):
    """这个 goal 定下来的技能（日志里最后一条 skill 行），没有返回 None。"""
    picks = [r['arg']['skill'] for r in read(gid) if r['kind'] == 'skill' and 'skill' in r['arg']]
    return SkillLoader(picks[-1]) if picks else None


def model_failed(ui):
    """模型没回（断网 / key 错 / 限流）：记一行，这轮先结束。RETRY_S 秒内 goal hook 不再放行。"""
    log('llm_fail', 'llm', {}, '模型没回')
    ui['action'] = 'wait'


def finish(g, why):
    g.finish()
    log('finish', 'goal', {'goal': int(g.id)}, '%s：%s' % (g.name, why))


# ---------- 收 ----------

def _save_jpeg(b64, prefix):
    os.makedirs(CACHE, exist_ok=True)
    name = '%s_%s_%03d.jpg' % (prefix, time.strftime('%H%M%S'), int(time.time() * 1000) % 1000)
    with open(os.path.join(CACHE, name), 'wb') as f:
        f.write(base64.b64decode(b64))
    return 'cache/' + name


def _on_message(name, item):
    if name == 'asr':
        name_, content = '回应当面说话', '有人当面对我说：「%s」。用 tts 回应。' % item
    elif name == '_sub/feishu':
        name_, content = '回应飞书消息', ('飞书上有人发来：「%s」。用 _pub/feishu 回复，不写 chat_id 就回到原会话。'
                                     % (item.get('text') or '[一张图片]'))
    else:
        name_, content = '处理到点提醒', item['text']
    g = GoalLoader.new(make_goal(name_, content))
    log('goal', 'goal', {'goal': int(g.id)}, content)


def _on_receipt(name, item):
    if name == '_sub/desktop' and item.get('type') == 'screen':
        text = '截图 %sx%s 已存 %s' % (item['width'], item['height'], _save_jpeg(item['data'], 'screen'))
    elif name == '_sub/desktop':
        text = '桌面做完了 %s' % json.dumps(item.get('command'), ensure_ascii=False)
    elif name == 'sub/leg':
        text = '腿回执 %s' % item.payload.decode('utf-8', 'replace')
    else:
        photo = json.loads(item.payload)
        text = '拍到照片 %sx%s 已存 %s' % (photo['width'], photo['height'], _save_jpeg(photo['data'], 'photo'))
    acts = [r for r in read() if r['kind'] == 'act']          # 回执算在最近做动作的 goal 上
    log('receipt', name, {'goal': acts[-1]['arg']['goal'] if acts else None}, text)


def _collect(queues):
    for name in INBOX + RECEIPTS:
        q = queues.get(name)
        while q is not None:
            try:
                item = q.get_nowait()
            except queue.Empty:
                break
            try:
                (_on_message if name in INBOX else _on_receipt)(name, item)
            except Exception as e:
                print('[brain] goal 丢弃 %s 的坏载荷: %r' % (name, e), flush=True)


# ---------- 选 ----------

def _current():
    while True:
        roots = [g for g in map(GoalLoader, GoalLoader.ids()) if g.father is None and not g.finish_time]
        if not roots:
            return None
        node = min(roots, key=lambda g: (g.id == '1', int(g.id)))
        while True:
            kids = [GoalLoader(c) for c in node.children]
            todo = [k for k in kids if not k.finish_time]
            if not kids:
                return node
            if not todo:
                finish(node, '子目标全部完成')
                break                            # 从根重新选
            node = todo[0]


# ---------- 判 ----------

def _seconds_ago(row):
    t = time.strptime(time.strftime('%Y-%m-%d ') + row['t'], '%Y-%m-%d %H:%M:%S')
    return time.time() - time.mktime(t)


def _check(self, g):
    ui, gid = self.user_info, int(g.id)
    rows = read(gid)
    acts = [i for i, r in enumerate(rows) if r['kind'] == 'act']
    checks = [i for i, r in enumerate(rows) if r['kind'] == 'check']
    if not acts or (checks and checks[-1] > acts[-1]):
        return                                   # 还没做过动作，或已经判过

    last = rows[acts[-1]]
    waiting = last['who'] in HAS_RECEIPT and not any(r['kind'] == 'receipt' for r in rows[acts[-1]:])
    if waiting and _seconds_ago(last) < RECEIPT_S:
        ui['action'] = 'wait'                    # 回执还没到，这轮先结束
        return
    if len(acts) >= MAX_ACTS:
        finish(g, '做了 %d 次动作还没完成，放弃' % len(acts))
        ui['goal'] = None
        return

    reply = call_llm(context(g, ASK_CHECK, chosen_skill(gid), history(gid)), max_tokens=2)
    if reply is None:
        model_failed(ui)
        return
    done = reply.strip().startswith('是')
    log('check', 'goal', {'goal': gid}, '完成' if done else '未完成')
    if done:
        finish(g, '检查通过')
        ui['goal'] = None


def hook(self):
    ui = self.user_info
    if ui.get('action'):
        return
    _collect(self.queues)
    rows = read()
    if rows and rows[-1]['kind'] == 'llm_fail' and _seconds_ago(rows[-1]) < RETRY_S:
        ui['action'] = 'wait'                    # 刚调不通，先别调；有新消息进来就不是最后一行了
        return
    ui['goal'] = _current()
    if ui['goal'] is None:
        ui['action'] = 'idle'                    # 没事可做
        return
    _check(self, ui['goal'])
