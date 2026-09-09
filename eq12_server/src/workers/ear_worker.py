from __future__ import annotations   # 延迟求值注解:Callback 里可前向引用后定义的 EarWorker

from queue import Queue
import os
import sys
import time

import dashscope
from dashscope.audio.asr import Recognition, RecognitionCallback, RecognitionResult

# ---------- 配置 ----------
# API Key 优先从环境变量读取；也可以直接写 dashscope.api_key = 'sk-xxx'
dashscope.api_key = os.environ.get('DASHSCOPE_API_KEY', '')
SAMPLE_RATE = 16000   # 支持 8000 / 16000
CHANNELS = 1          # 单声道
BLOCK_SIZE = 512      # PyAudio 每次读取的帧数(喂 ASR 无 512 限制，此处仅为读块大小)
FORMAT = 'pcm'        # int16 pcm

class Callback(RecognitionCallback):
    """把每一帧识别结果实时打印到终端。"""
    def __init__(self, obj:EarWorker):
        self.obj = obj

    def on_open(self):
        print('[ASR] 连接已建立，请开始说话...', flush=True)

    def on_close(self):
        print('[ASR] 连接已关闭', flush=True)

    def on_error(self, result):
        # dashscope 的 RecognitionResult.__str__ 偶尔缺 headers 属性会抛异常，
        # 若让异常从这里冒出去，dashscope 的 ASR 接收线程会直接死掉(之后无法识别)。
        # 这里兜底：能打印就打印，打印不了只报类型，绝不让线程挂。
        try:
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
                self.obj.queues['asr'].put(text)

class EarWorker:
    """每器官一个 worker：消费 sub/ear 入站队列做 ASR 等。

    stop_token 是主循环停机时投进 sub/* 队列的 _STOP 哨兵对象，
    run() get() 到它即退出（不把它当业务数据处理），用于优雅停机。
    """

    def __init__(self, queues: dict[str, Queue], stop_token=None):
        self.queues = queues
        self.stop_token = stop_token

    def run(self):
        # 持续把 sub/ear 音频送 ASR。dashscope 会话可能中途结束(空闲关闭/
        # 云端错误/网络抖动),此时 send_audio_frame 会抛异常——不能让它杀死
        # worker 线程,否则之后所有语音都不再被识别;要自动重建会话继续服务。
        recognition = self._new_recognition()
        while True:
            item = self.queues['sub/ear'].get()
            if self.stop_token is not None and item is self.stop_token:
                break
            sound = item.payload
            try:
                # 发送方向按协议约定：若大脑订阅 pub/brain 则写 self.queues['pub/brain']
                recognition.send_audio_frame(sound)
            except Exception as e:
                # 会话已停/未就绪:丢当前帧,节流后重建(重启期间的语音会丢
                # 一小段,但线程不会死,恢复后继续识别)
                print('[ASR] 会话异常,自动重启识别: %s' % e, flush=True)
                time.sleep(1.0)
                try:
                    recognition.stop()
                except Exception:
                    pass
                recognition = self._new_recognition()

    def _new_recognition(self):
        recognition = Recognition(
            model='qwen-audio-3.0-asr-flash-streaming',
            format=FORMAT,
            sample_rate=SAMPLE_RATE,
            semantic_punctuation_enabled=True,  # 开启标点，便于判断一句话结束
            callback=Callback(self),
        )
        recognition.start()
        return recognition
