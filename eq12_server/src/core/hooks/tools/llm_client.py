import json
import os

import requests
import openai
from openai import OpenAI
# from ....config import (LLM_MAX_TOKENS, LLM_MODEL, LLM_MODEL_VL,
#                         LLM_TEMPERATURE, LLM_TIMEOUT, SILICONFLOW_API_KEY,
#                         SILICONFLOW_BASE)

# ======================= 大脑 / 大模型（硅基流动 SiliconFlow，OpenAI 兼容）=======================
SILICONFLOW_API_KEY = os.environ.get('SILICONFLOW_API_KEY', '')
SILICONFLOW_BASE = 'https://api.siliconflow.cn/v1'
LLM_MODEL = 'deepseek-ai/DeepSeek-V4.1-Flash'          # 纯文本
# 4-5秒

DEEPSEEK_API_KEY = os.environ.get('DEEPSEEK_API_KEY', '')
DEEPSEEK_BASE = 'https://api.deepseek.com/v1'
LLM_MODEL = 'deepseek-flash'          # 纯文本


LLM_MAX_TOKENS = 2048
LLM_TEMPERATURE = 0.3
LLM_TIMEOUT = 60              # 秒

# client = OpenAI(
#     api_key=SILICONFLOW_API_KEY,
#     base_url=SILICONFLOW_BASE
# )

client = OpenAI(
    api_key=DEEPSEEK_API_KEY,
    base_url=DEEPSEEK_BASE
)

def call_llm(messages, max_tokens=LLM_MAX_TOKENS, enable_thinking=False):
    extra_body = {}
    if not enable_thinking:
        extra_body = {
            'enable_thinking': False,
            "thinking": {"type": "disabled"},
        }

    response = client.chat.completions.create(
        model=LLM_MODEL,
        messages=messages,
        max_tokens=max_tokens,
        extra_body=extra_body
    )
    print(response)

if __name__ == '__main__':
    import base64

    path = r"images\test.jpg"

    with open(path, "rb") as f:
        b64 = base64.b64encode(f.read()).decode("ascii")

    data_url = f"data:image/jpeg;base64,{b64}"
    messages = [
        # {"role": "user", "content": },
        {"role": "user", "content": [{"type": "image_url", "image_url": {"url": data_url}}, {"type": "text", "text": "这张图片是什么？"}]}
    ]
    import time
    cur_time = time.time()
    # 4秒-5秒
    call_llm(messages=messages)
    print(time.time() - cur_time)

