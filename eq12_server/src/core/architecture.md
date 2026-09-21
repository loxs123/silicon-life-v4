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

## 几条约定

- 私有常量放自己文件顶部（同 `ear_worker.py` 的 `SAMPLE_RATE` 风格）；跨 hook 共用的才上 `src/config.py`
- 文件头 docstring 写清「读什么 / 写什么」
- hook 里别 `sleep`、别自己开线程——会拖住 brain 主循环
- 写完在 `hooks/__init__.py` 里按顺序注册，文件不会自动被发现
