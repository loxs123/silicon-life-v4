"""llm_client 冒烟测试：不联网、不装 dashscope（用假模块顶替）。

跑法（在 eq12_server/ 目录下）：
    python tests/test_llm_client.py

覆盖：
  1. 默认参数：max_tokens=MAX_TOKENS、enable_thinking=False、不传 thinking_budget，
     且 stream=False / result_format='message'
  2. 传参：max_tokens 和 thinking_budget 原样到请求里；thinking_budget=0 = 关闭思考
  3. 失败路径：status_code != 200 / 调用抛异常 → 返回 None；
     缺 DASHSCOPE_API_KEY → KeyError（现在的代码就是直接索引环境变量，不兜底）
"""
import os
import sys
import types

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

# 本机可能没装 dashscope：先塞一个假的进 sys.modules，llm_client 才会拿到能用的 SDK
class FakeResponse:
    def __init__(self, code, content, message=''):
        self.status_code = code
        self.message = message
        self.output = types.SimpleNamespace(
            choices=[types.SimpleNamespace(
                message=types.SimpleNamespace(content=content))])


class FakeGeneration(object):
    def __init__(self):
        self.calls = []

    def call(self, **kwargs):
        self.calls.append(kwargs)
        if kwargs['model'] == 'boom':
            raise RuntimeError('网络断了')
        if kwargs['model'] == 'bad':
            return FakeResponse(500, None, 'InternalError')
        return FakeResponse(200, '我在呢。')


_fake = types.ModuleType('dashscope')
_fake.api_key = ''
_fake.Generation = FakeGeneration()
sys.modules['dashscope'] = _fake

from src.core.hooks.tools import llm_client  # noqa: E402

MSGS = [{'role': 'user', 'content': '你好'}]


def test_defaults():
    os.environ['DASHSCOPE_API_KEY'] = 'sk-test'
    _fake.Generation.calls = []
    out = llm_client.call_llm(MSGS)
    assert out == '我在呢。', out
    (call,) = _fake.Generation.calls
    assert call['messages'] is MSGS, call                 # messages 原样发出去
    assert call['stream'] is False, call                  # 非流式
    assert call['result_format'] == 'message', call
    assert call['max_tokens'] == llm_client.MAX_TOKENS, call
    assert call['enable_thinking'] is False, call         # 默认不思考
    assert 'thinking_budget' not in call, call            # 关了就别带 budget
    assert _fake.api_key == 'sk-test', _fake.api_key      # 设到 SDK 上了


def test_custom_params():
    _fake.Generation.calls = []
    assert llm_client.call_llm(MSGS, max_tokens=512,
                               thinking_budget=1024) == '我在呢。'
    (call,) = _fake.Generation.calls
    assert call['max_tokens'] == 512, call
    assert call['enable_thinking'] is True, call          # budget > 0 = 开思考
    assert call['thinking_budget'] == 1024, call


def test_max_tokens_none_omitted():
    _fake.Generation.calls = []
    llm_client.call_llm(MSGS, max_tokens=None)            # None = 不设上限
    (call,) = _fake.Generation.calls
    assert 'max_tokens' not in call, call


def test_fail_paths():
    # 1) 接口返回非 200
    assert llm_client.call_llm(MSGS, model='bad') is None
    # 2) 调用直接抛异常
    assert llm_client.call_llm(MSGS, model='boom') is None
    # 3) 缺 key：直接 KeyError（不降级）
    os.environ.pop('DASHSCOPE_API_KEY', None)
    try:
        llm_client.call_llm(MSGS)
    except KeyError:
        pass
    else:
        raise AssertionError('缺 DASHSCOPE_API_KEY 应当 KeyError')


def main():
    test_defaults()
    test_custom_params()
    test_max_tokens_none_omitted()
    test_fail_paths()
    print('LLM CLIENT TEST PASS: 默认参数 / max_tokens / 思考程度 / 失败路径 全通过')


if __name__ == '__main__':
    main()
