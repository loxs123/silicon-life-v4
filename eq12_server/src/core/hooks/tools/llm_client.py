import os

try:
    import dashscope
except ImportError:
    dashscope = None

from . import loader
from .loader import GoalLoader, MemoryLoader, SkillLoader, day_dir

MODEL = 'qwen-plus'        # 换模型只改这里
MAX_TOKENS = 2048          # 默认输出上限（生成结果只会 <= 它）
THINKING_BUDGET = 0        # 默认不思考：想得越久越慢越贵，闲聊别开


def call_llm(messages, model=MODEL, max_tokens=MAX_TOKENS,
             thinking_budget=THINKING_BUDGET):
    """问一句、拿整段回复。成功返回字符串，失败返回 None。

    参数：
        max_tokens     输出上限（token）。
        thinking_budget 思考程度：给思考过程留多少 token，0 = 关掉思考模式
                       （qwen-plus 上限 32768，越大想得越久）。
    """
    if dashscope is None:
        print('[llm] 没装 dashscope，跳过调用（pip install dashscope）', flush=True)
        return None
    dashscope.api_key = os.environ.get('DASHSCOPE_API_KEY', '')
    kwargs = {
        'result_format': 'message',   # 要 message 结构，好取 content
        'stream': False,              # 非流式：一次拿完
        'enable_thinking': bool(thinking_budget),
    }
    if max_tokens:
        kwargs['max_tokens'] = max_tokens
    if thinking_budget:
        kwargs['thinking_budget'] = thinking_budget
    try:
        resp = dashscope.Generation.call(model=model, messages=messages,
                                         **kwargs)
    except Exception as e:
        print('[llm] 请求异常: %s' % e, flush=True)
        return None
    if resp.status_code != 200:
        print('[llm] 失败 %s: %s' % (resp.status_code, resp.message), flush=True)
        return None
    return resp.output.choices[0].message.content


def xml(text):
    """从模型回复里取出最外层 XML：去掉 ``` 围栏，截到最后一个 '>'。"""
    text = (text or '').strip()
    if text.startswith('```'):
        text = text.split('\n', 1)[-1]
    text = text.rstrip('`').strip()
    i, j = text.find('<'), text.rfind('>')
    return text[i:j + 1] if 0 <= i < j else ''


# ---------- 统一上下文：所有调用同一个消息序列，越稳定越靠前，好吃前缀缓存 ----------
#
#   system  memory/<今天>/self.xml 的 <content>       一天不变（夜里 dream 才改）
#   user    # 子目标格式 / # 原子动作格式               一天不变
#   user    # 元技能：造技能 / # 元技能：写记忆         一天不变
#   user    # 我记得的事                               写新记忆才变
#   user    # 我现有的技能                             造新技能才变
#   user    # 目标链 / # 当前目标                      同一个 goal 不变
#   user    # 所用技能                                 选定后不变（没选就没有这条）
#   user    # 经过                                     只往后加
#   user    # 现在要做                                 每种调用不同
# 每段一条消息，不全塞 system。

RECENT_MEMORY = 10
SELF = 'self'          # memory/<今天>/self.xml：我是谁，作 system；不进「我记得的事」


def _read(path):
    with open(path, encoding='utf-8') as f:
        return f.read().strip()


def skills():
    """「我现有的技能」里列出的技能，编号从 1 开始（选技能时按这个编号回答）。"""
    return [s for s in SkillLoader.all() if s.type in ('子目标', '原子动作')]


def context(goal, ask, skill=None, history='（还没开始）'):
    """拼一次调用的 messages。goal / skill 是 loader；history 是「经过」；ask 是最后一句要求。"""
    protocols = os.path.join(loader.HOOKS_DIR, 'protocols')
    mems = [m for m in MemoryLoader.all() if m._id != SELF][-RECENT_MEMORY:]
    chain = [goal]
    while chain[0].father is not None:
        chain.insert(0, GoalLoader(chain[0].father))

    parts = [
        '# 子目标格式\n' + _read(os.path.join(protocols, 'sub_goal.xml')),
        '# 原子动作格式\n' + _read(os.path.join(protocols, 'atom_action.xml')),
        '# 元技能：造技能\n' + _read(os.path.join(day_dir('skills'), 'skill_creator.xml')),
        '# 元技能：写记忆\n' + _read(os.path.join(day_dir('skills'), 'memory_creator.xml')),
        '# 我记得的事\n' + ('\n'.join('- %s：%s' % (m.name, m.content) for m in mems) or '（还没有）'),
        '# 我现有的技能\n' + ('\n'.join('%d. %s（%s）：%s｜什么时候用：%s' % (i, s.name, s.type, s.description, s.target)
                                   for i, s in enumerate(skills(), 1)) or '（还没有）'),
        '# 目标链\n' + '\n'.join('%s- %s：%s' % ('  ' * i, g.name, g.content) for i, g in enumerate(chain)),
        '# 当前目标\n' + goal.raw,
    ]
    if skill is not None:
        parts.append('# 所用技能\n' + skill.raw)
    parts += ['# 经过\n' + history, '# 现在要做\n' + ask]
    return ([{'role': 'system', 'content': MemoryLoader(SELF).content.strip()}]
            + [{'role': 'user', 'content': p} for p in parts])


if __name__ == '__main__':
    messages = [{"role": "user", "content": '用一句话介绍你自己'}]
    print(call_llm(messages))
    print(call_llm(messages, max_tokens=512, thinking_budget=1024))  # 短一点、带思考
