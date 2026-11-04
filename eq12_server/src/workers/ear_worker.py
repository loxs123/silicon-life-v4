from __future__ import annotations   # Callback 里前向引用 EarWorker

from queue import Queue
import time

import dashscope
from dashscope.audio.asr import Recognition, RecognitionCallback, RecognitionResult

from ..config import (ASR_FORMAT, ASR_MODEL, ASR_SAMPLE_RATE,
                      DASHSCOPE_API_KEY, QUEUE_ASR, QUEUE_EAR_IN)

dashscope.api_key = DASHSCOPE_API_KEY

class Callback(RecognitionCallback):
    def __init__(self, obj:EarWorker):
        self.obj = obj

    def on_open(self):
        print('[ASR] 连接已建立，请开始说话...', flush=True)

    def on_close(self):
        print('[ASR] 连接已关闭', flush=True)

    def on_error(self, result):
        try:            # result 的 __str__ 会抛，别让它杀掉 ASR 接收线程
            print('[ASR] 出错:', result, flush=True)
        except Exception as e:
            print('[ASR] 出错(结果无法打印, 类型 %s): %s'
                  % (type(result).__name__, e), flush=True)

    def on_event(self, result: RecognitionResult):
        sentence = result.get_sentence()
        if sentence and 'text' in sentence and sentence['text']:
            text = sentence['text']
            if sentence['sentence_end'] and text:
                print(f'[done]{text}')
                self.obj.queues[QUEUE_ASR].put(text)

class EarWorker:
    def __init__(self, queues: dict[str, Queue], stop_token=None):
        self.queues = queues
        self.stop_token = stop_token

    def run(self):
        recognition = self._new_recognition()
        while True:
            item = self.queues[QUEUE_EAR_IN].get()
            if self.stop_token is not None and item is self.stop_token:
                break
            sound = item.payload
            try:
                recognition.send_audio_frame(sound)
            except Exception as e:     # 会话断了就重建，线程不能死
                print('[ASR] 会话异常,自动重启识别: %s' % e, flush=True)
                time.sleep(1.0)
                try:
                    recognition.stop()
                except Exception:
                    pass
                recognition = self._new_recognition()

    def _new_recognition(self):
        recognition = Recognition(
            model=ASR_MODEL,
            format=ASR_FORMAT,
            sample_rate=ASR_SAMPLE_RATE,
            semantic_punctuation_enabled=True,
            callback=Callback(self),
        )
        recognition.start()
        return recognition
