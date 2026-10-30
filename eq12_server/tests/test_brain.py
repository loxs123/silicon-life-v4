"""白天大脑全链路冒烟测试：不联网、不装 dashscope，临时 hooks 目录 + 剧本化的假模型。

跑法（在 eq12_server/ 目录下）：
    python tests/test_brain.py

一切按 protocols/：goal / skill / memory 都是 XML 文件，经 tools/loader.py 读写、tools/checker.py 校验。
Pipeline.process() 一直跑 hook，直到产生具体动作（或无事可做 / 等回执）。

剧本：
  A 有人当面说"你好" → 建 goal 2 → 选技能（没有）→ skill_creator 造「回话」→ 执行 → tts
  B 检查 goal 2 完成 → 写记忆 → 计划 goal 1 用 plan 技能拆成 3、4 → goal 3 造「截屏发飞书」→ 截屏
  C 截图回执还没到 → 不阻塞，这一轮直接结束
  D 回执到了 → 检查未完成 → 发飞书图片
  E 检查完成 → 记忆判不值得记 → goal 4 复用「回话」→ tts
  F 检查完成 → goal 1 子目标全完成 → 无事可做
"""
import base64
import glob
import importlib
import json
import os
import queue
import shutil
import sys
import tempfile
import types

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

_fake = types.ModuleType('dashscope')
_fake.api_key = ''
_fake.Generation = types.SimpleNamespace()
sys.modules['dashscope'] = _fake

from src.core.pipeline import Pipeline  # noqa: E402

loader = importlib.import_module('src.core.hooks.tools.loader')
logmod = importlib.import_module('src.core.log')
goal = importlib.import_module('src.core.hooks.goal')
skill = importlib.import_module('src.core.hooks.skill')
memory = importlib.import_module('src.core.hooks.memory')
llm_client = importlib.import_module('src.core.hooks.tools.llm_client')

QUEUES = ('asr', 'tts', '_sub/feishu', '_pub/feishu', '_sub/delay', '_pub/delay',
          '_sub/desktop', '_pub/desktop', 'sub/leg', 'pub/leg', 'sub/eye', 'pub/eye', 'pub/face')
JPEG = b'\xff\xd8fake-jpeg\xff\xd9'

SKILL_TALK = '''<skill><id></id><type>原子动作</type><name>回话</name>
<tags><tag>对话</tag></tags><description>用一句话回应别人</description>
<target>有人跟我说话、需要回一句的时候</target>
<steps><step><step-name>回一句</step-name><step-content>投 tts 一句话</step-content></step></steps>
<notes><note>别太长</note></notes><verify>已经投出一句回应</verify><output>说了什么</output></skill>'''

SKILL_SHOT = SKILL_TALK.replace('回话', '截屏发飞书').replace('用一句话回应别人', '截屏后把图发到飞书') \
    .replace('有人跟我说话、需要回一句的时候', '要把屏幕给别人看的时候').replace('已经投出一句回应', '飞书里能看到图')

# (这次调用的提示词里应当出现的字, 假模型的回复)
SCRIPT = [
    # A
    ('只回答编号', '0'),
    ('照元技能「造技能」', SKILL_TALK),
    ('「原子动作格式」写出', '<atom_actions><atom_action><queue>tts</queue><text>你好呀</text></atom_action></atom_actions>'),
    # B
    ('只回答一个字', '是'),
    ('照元技能「写记忆」', '<memory><id></id><name>有人跟我打招呼</name><tags><tag>对话</tag></tags>'
                       '<description>当面</description><content>有人说你好，我回了你好呀</content>'
                       '<time>2026-10-30 10:00:00</time></memory>'),
    ('「子目标格式」拆出', '```xml\n<sub_goals><sub_goal><name>07:00-15:00</name><content>截个屏发到飞书</content></sub_goal>'
                 '<sub_goal><name>15:00-23:00</name><content>说一句发好了</content></sub_goal></sub_goals>\n```'),
    ('只回答编号', '0'),
    ('照元技能「造技能」', SKILL_SHOT),
    ('「原子动作格式」写出', '<atom_actions><atom_action><queue>_pub/desktop</queue><type>screenshot</type>'
              '</atom_action></atom_actions>'),
    # D
    ('只回答一个字', '否'),
    ('「原子动作格式」写出', None),                # 发图：路径从「经过」里抠
    # E
    ('只回答一个字', '是'),
    ('照元技能「写记忆」', '<none/>'),
    ('只回答编号', '2'),
    ('「原子动作格式」写出', '<atom_actions><atom_action><queue>tts</queue><text>发好了</text></atom_action></atom_actions>'),
    # F
    ('只回答一个字', '是'),
    ('照元技能「写记忆」', '<none/>'),
]


class Harness:
    def __init__(self):
        self.dir = tempfile.mkdtemp(prefix='brain_test_')
        hooks = os.path.join(self.dir, 'src', 'core', 'hooks')
        for sub in ('memory/seed', 'skills/seed', 'protocols'):
            shutil.copytree(os.path.join(loader.HOOKS_DIR, sub), os.path.join(hooks, sub))
        self.orig = (loader.HOOKS_DIR, logmod.LOGS, skill.EQ12_DIR, goal.CACHE,
                     goal.call_llm, skill.call_llm, memory.call_llm)
        loader.HOOKS_DIR = hooks
        logmod.LOGS = os.path.join(hooks, 'logs')
        skill.EQ12_DIR = self.dir
        goal.CACHE = os.path.join(self.dir, 'cache')
        goal.call_llm = skill.call_llm = memory.call_llm = self.llm
        self.hooks = hooks
        self.n = 0
        self.queues = {n: queue.Queue() for n in QUEUES}

    def llm(self, messages, **kw):
        text = '\n'.join(m['content'] for m in messages)
        ask = messages[-1]['content']
        expect, reply = SCRIPT[self.n]
        assert expect in ask, '第 %d 次调用应含 %r：\n%s' % (self.n + 1, expect, ask)
        self.n += 1
        if reply is None:
            path = text[text.rindex('cache/screen_'):].split()[0]
            reply = ('<atom_actions><atom_action><queue>_pub/feishu</queue><img>%s</img>'
                     '</atom_action></atom_actions>' % path)
        return reply

    def drain(self, name):
        out = []
        while not self.queues[name].empty():
            out.append(self.queues[name].get())
        return out

    def close(self):
        (loader.HOOKS_DIR, logmod.LOGS, skill.EQ12_DIR, goal.CACHE,
         goal.call_llm, skill.call_llm, memory.call_llm) = self.orig
        shutil.rmtree(self.dir, ignore_errors=True)


def main():
    h = Harness()
    try:
        p = Pipeline(h.queues)
        G = loader.GoalLoader

        h.queues['asr'].put('你好')
        p.process()                                                       # A
        assert h.drain('tts') == ['你好呀'] and h.n == 3
        assert loader.SkillLoader(1).name == '回话'

        p.process()                                                       # B
        assert h.drain('_pub/desktop') == [{'type': 'screenshot'}] and h.n == 9
        assert G(2).finish_time and G(1).children == [3, 4]
        assert G(3).father == 1
        assert loader.MemoryLoader(1).name == '有人跟我打招呼'
        msgs = llm_client.context(G(3), '…')
        assert msgs[0]['role'] == 'system' and msgs[-1]['content'] == '# 现在要做\n…'
        assert msgs[0]['content'].startswith('我是一个硅基生命。')                # system = self.xml 的 content
        assert '我是谁' not in msgs[5]['content']                           # self 不进「我记得的事」
        assert '- 有人跟我打招呼：' in msgs[5]['content']                    # 记忆进了上下文
        assert all(' id="' not in m['content'] for m in msgs)                          # 不带元素编号
        assert '<![CDATA[' in msgs[3]['content']                           # 元技能原文，没被转义

        p.process()                                                       # C：不等回执
        assert p.user_info['action'] == 'wait' and h.n == 9

        h.queues['_sub/desktop'].put({'type': 'done', 'command': {'type': 'screenshot'}})
        h.queues['_sub/desktop'].put({'type': 'screen', 'width': 8, 'height': 6, 'size': len(JPEG),
                                      'data': base64.b64encode(JPEG).decode()})
        p.process()                                                       # D
        sent = h.drain('_pub/feishu')
        assert len(sent) == 1 and base64.b64decode(sent[0]['img']) == JPEG, sent

        p.process()                                                       # E
        assert h.drain('tts') == ['发好了']
        assert [r['arg']['skill'] for r in logmod.read(4) if r['kind'] == 'skill'] == [1]   # 复用

        p.process()                                                       # F
        assert p.user_info['action'] == 'idle' and h.n == len(SCRIPT)
        assert all(G(i).finish_time for i in G.ids())

        for i in G.ids():                                                 # 落盘的都符合协议
            assert goal_ok(i), G(i).text
        for path in glob.glob(os.path.join(h.hooks, '*', '2*', '*.xml')):
            with open(path, encoding='utf-8') as f:
                assert ' id="' not in f.read(), path                     # 元素编号不落盘
        with open(os.path.join(logmod.LOGS, os.listdir(logmod.LOGS)[0]), encoding='utf-8') as f:
            assert not any('fake-jpeg' in line for line in f)
    finally:
        h.close()
    print('BRAIN TEST PASS: 造技能 / 回话 / 检查 / 记忆 / plan 拆目标 / 回执异步 / 发图 / 复用技能 / 冒泡完成 全通过')


def goal_ok(i):
    from src.core.hooks.tools.checker import check
    return check(loader.GoalLoader(i).text, 'goal') == ''


if __name__ == '__main__':
    main()
