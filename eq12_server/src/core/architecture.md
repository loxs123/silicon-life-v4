# hook 编写指南

一个 hook = **一个文件 + 一个函数**，放在 `src/core/hooks/`。

## 怎么写

```python
# src/core/hooks/llm_stream.py

def llm_stream(self):
    ...
```

**函数名 = 文件名**，第一个参数是 `self`，通过它拿到 Pipeline 上的一切。

## self 上有什么

| 属性 | 用途 |
|---|---|
| `self.queues` | 队列字典，`self.queues['tts'].put(...)` |
| `self.user_info` | 本轮数据，放输入、中间结果、最终 `output` |
| `self.cache_dir` | 缓存目录 |

## 往队列里加东西 —— 必须写日志

**规矩：只要 hook 往队列里 `put`，就必须在紧挨着的地方打一行日志。**
队列是跨线程的，出了问题只能靠日志回溯是谁在什么时候塞了什么。

```python
def route_intent(self):
    reply = '好，我记下了。'
    self.queues['tts'].put(reply)
    print('[brain] route_intent → tts: %s' % reply, flush=True)
```

日志就照这个格式：`[brain] <hook名> → <队列名>: <内容摘要>`

- 前缀统一 `[brain]`，和现有 worker 的 `[TTS]` / `[ASR]` 风格一致
- **hook 名和目标队列名都要带**，否则定位不到是谁投的
- 内容太长就截断
- `flush=True` 不能省，否则重定向到文件时看不到

反过来，只写 `self.user_info[...]` 而不投队列的 hook，不需要日志。

## 完整例子

```python
# src/core/hooks/llm_stream.py
"""[生成] 流式调模型，凑到句末标点就投 tts。

读: self.user_info['messages']
写: self.user_info['output']
"""
import os
import re

import dashscope

dashscope.api_key = os.environ.get('DASHSCOPE_API_KEY', '')   # 同现有 worker 风格
MODEL = 'qwen-plus'
SENT_END = re.compile(r'[。！？!?]')           # 与 brain_worker 现有常量一致


def llm_stream(self):
    buf = full = ''
    for resp in dashscope.Generation.call(
            model=MODEL,
            messages=self.user_info['messages'],
            result_format='message',
            stream=True,
            incremental_output=True):
        delta = resp.output.choices[0].message.content or ''
        buf += delta
        full += delta
        m = SENT_END.search(buf)
        while m:                              # 成句即送，不等整段生成完
            sent, buf = buf[:m.end()], buf[m.end():]
            if sent.strip():
                self.queues['tts'].put(sent)
                print('[brain] llm_stream → tts: %s' % sent, flush=True)
            m = SENT_END.search(buf)
    if buf.strip():                           # 收尾那段没标点的
        self.queues['tts'].put(buf)
        print('[brain] llm_stream → tts: %s' % buf, flush=True)
    self.user_info['output'] = full
```

## 桌面版可运行示例（不接 ESP32）

`hook_examples/` 是一条**只在这台电脑上**跑得通的链：飞书进来 → 看/动本机屏幕键鼠
→ 飞书回文字 + 图片，四个 ESP32 主题一个都不用，也不需要 broker 和飞书凭据：

```bash
cd eq12_server && python -m src.core.hook_examples.demo
```

六个 hook、队列怎么配对、两个已发现的坑（`read_screen` 的有界等待、
`_sub/desktop` 上 `done`/`screen` 的先后和文档不一致），都写在
`hook_examples/README.md` 里。

## 几条约定

- hook 自己的私有常量放文件顶部；**worker 的参数一律放 `src/config.py`**
  （模型名、采样率、音色、超时、音量、JPEG 质量、队列名…），worker 里只 import 不自己定义，
  见 config.py 里按 `耳朵 / ASR`、`嘴 / TTS`、`飞书`、`桌面` 分的段
- 文件头 docstring 写清「读什么 / 写什么」
- hook 里别 `sleep`、别自己开线程——会拖住 brain 主循环
- 写完在 `hooks/__init__.py` 里按顺序注册，文件不会自动被发现
