from queue import Queue
import os
import sys

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
        print('[ASR] 出错:', result, flush=True)

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
        # 2. 启动流式识别
        recognition = Recognition(
            model='qwen-audio-3.0-asr-flash-streaming',
            format=FORMAT,
            sample_rate=SAMPLE_RATE,
            semantic_punctuation_enabled=True,  # 开启标点，便于判断一句话结束
            callback=Callback(self),
        )
        recognition.start()
        while True:
            item = self.queues['sub/ear'].get()
            if self.stop_token is not None and item is self.stop_token:
                break
            sound = item.payload
            # 发送方向按协议约定：若大脑订阅 pub/brain 则写 self.queues['pub/brain']
            recognition.send_audio_frame(sound)
