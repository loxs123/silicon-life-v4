"""
BrainWorker —— "大脑"器官:ASR 文本进来,流式调大模型,成句即送 TTS
====================================================================

数据流位置:
    sub/ear 原始音频 → EarWorker(ASR) → queues['asr']   ← 本 worker 在此消费
    BrainWorker(流式 LLM) → queues['tts'] → SpeakWorker(TTS)
        → queues['pub/speak'] → MQTT → ESP32 出声

每当 asr 队列来一条完整识别文本(ear_worker 只在 sentence_end 时投,即一个
完整句子),就流式调用一次大模型(stream=True + incremental_output=True,
首字尽可能早到)。流式增量里**每凑成一个完整句子(以 。！？!? 结尾)就立刻
整句投进 tts 队列**,不必等整段回复收齐 —— SpeakWorker 可以边说这句、边等
模型生成下一句(TTS 是"一句一文本"地合成,所以只送完整句,不送半截增量,
避免说出残缺的话;模型收尾时若还有不带句号的话尾巴,也作为最后一句送出)。

对话记忆:进程内保留最近 MAX_HISTORY 条历史(含人设 system 消息),让"硅基
生命"能接上下文;超过上限丢弃最老的对话,防上下文无限膨胀。历史里存的是
模型整段回复(由各句拼回),与听到的每句都能对上。

worker 骨架(队列循环 / stop_token / 优雅停机)对齐 ear_worker.py。停机说明
同 speak_worker:内部 asr/tts 队列不投 _STOP 哨兵,本 worker 是 daemon 线程,
随进程退出结束。

依赖:
    pip install dashscope
    set DASHSCOPE_API_KEY=sk-xxx
"""

import os
import re
import time
from http import HTTPStatus
from queue import Queue

import dashscope
from dashscope import Generation

# ---------- 配置 ----------
# API Key 优先从环境变量读取;也可以直接写 dashscope.api_key = 'sk-xxx'
dashscope.api_key = os.environ.get('DASHSCOPE_API_KEY', '')

INPUT_QUEUE = 'asr'   # 消费:内部流水线队列,ear_worker 投进来的识别文本
OUTPUT_QUEUE = 'tts'  # 产出:内部流水线队列,SpeakWorker 消费做 TTS

MODEL = 'qwen-plus'   # 对话模型;可换 qwen-flash(更快更省)/ qwen-turbo / qwen-max
SYSTEM_PROMPT = '你是 EQ12「硅基生命」机器人。回答要口语化、简短,一般一两句话,像在跟人面对面聊天。'
MAX_HISTORY = 12      # 保留的最近对话条数(不含 system)
REPLY_TIMEOUT = 60.0  # 单次回复最长等待秒数,防网络异常导致永久卡住
SENT_END = re.compile(r'[。！？!?]')   # 句末标点:流式输出里凑到它就切一句送给 TTS

class BrainWorker:
    """消费 asr 队列的文本,流式调用模型,把完整句子逐句投进 tts 队列。

    stop_token 是主循环停机时投进 pub/*、sub/* 队列的 _STOP 哨兵对象;
    run() get() 到它即退出(不把它当业务文本),用于优雅停机。
    """

    def __init__(self, queues: dict[str, Queue], stop_token=None):
        self.queues = queues
        self.stop_token = stop_token
        self.messages = [{'role': 'system', 'content': SYSTEM_PROMPT}]

    def run(self):
        if not dashscope.api_key:
            print('[Brain] 警告: 未设置 DASHSCOPE_API_KEY,调用将失败', flush=True)
        print('[Brain] BrainWorker 已启动,等待 %s 队列文本...' % INPUT_QUEUE,
              flush=True)
        while True:
            item = self.queues[INPUT_QUEUE].get()
            if self.stop_token is not None and item is self.stop_token:
                break
            text = item
            text = str(text).strip()
            if not text:
                continue
            self._reply(text)   # 阻塞到整段回复生成完;内部全兜底,不外抛

    # ------------------------------------------------------- 回复一句
    def _reply(self, text):
        print('[Brain] 听到: %s' % text[:80], flush=True)
        self.messages.append({'role': 'user', 'content': text})
        sentences = []   # 收到的完整句子(用于拼回整段回复,写进历史)
        try:
            # 每来一句完整的话,立刻投给 tts,不等模型把整段收齐
            for sent in self._stream_sentences():
                sentences.append(sent)
                self.queues[OUTPUT_QUEUE].put(sent)
                print('[Brain] → %s (%d 字,成句即送)'
                      % (sent[:60], len(sent)), flush=True)
        except Exception as e:
            # 中途失败:已送出的句子照播(收不回),剩余部分放弃
            print('[Brain] 调用中断,已送出的句子照播: %s' % e, flush=True)
            self.messages.pop()   # 撤掉没答完的用户消息,不污染后续上下文
            return
        reply = ''.join(sentences).strip()
        if not reply:
            print('[Brain] 模型无输出,本句放弃', flush=True)
            self.messages.pop()
            return
        self.messages.append({'role': 'assistant', 'content': reply})
        # 历史裁剪:只保留 system + 最近 MAX_HISTORY 条对话
        if len(self.messages) - 1 > MAX_HISTORY:
            self.messages = [self.messages[0]] + self.messages[-MAX_HISTORY:]
        print('[Brain] 整句回复完毕 (%d 字,共 %d 句送 tts)'
              % (len(reply), len(sentences)), flush=True)

    def _stream_sentences(self):
        """流式调用模型,边收边打印增量;凑成完整句子就 yield,流结束把
        没有句号的尾巴也作为最后一句 yield。异常沿生成器抛给调用方。"""
        buf = ''
        t0 = time.perf_counter()
        responses = Generation.call(model=MODEL,
                                    messages=self.messages,
                                    result_format='message',
                                    stream=True,
                                    incremental_output=True)
        for chunk in responses:
            if time.perf_counter() - t0 > REPLY_TIMEOUT:
                print('[Brain] 回复超时(%.0fs),按已收内容收尾'
                      % REPLY_TIMEOUT, flush=True)
                break
            if chunk.status_code != HTTPStatus.OK:
                raise RuntimeError('status=%s code=%s msg=%s' % (
                    chunk.status_code, chunk.code, chunk.message))
            delta = chunk.output.choices[0]['message']['content']
            if not delta:
                continue
            buf += delta
            print(delta, end='', flush=True)
            # 句末标点一到,立即把前面的完整句子切出去
            while True:
                m = SENT_END.search(buf)
                if m is None:
                    break
                sent = buf[:m.end()].strip()
                buf = buf[m.end():]
                if sent and any(ch.isalnum() for ch in sent):
                    yield sent
        print(flush=True)   # 收尾:结束上面行内流式打印
        tail = buf.strip()
        # 同上:纯 emoji 尾巴丢弃,避免最后一句 TTS 断连"没说完就停了"
        if tail and any(ch.isalnum() for ch in tail):
            yield tail
