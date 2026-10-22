import os
import dashscope

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
    dashscope.api_key = os.environ['DASHSCOPE_API_KEY']
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


if __name__ == '__main__':
    messages = [{"role": "user", "content": '用一句话介绍你自己'}]
    print(call_llm(messages))
    print(call_llm(messages, max_tokens=512, thinking_budget=1024))  # 短一点、带思考
