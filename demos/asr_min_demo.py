"""
ASR 最小 Demo
=============
麦克风采集 -> DashScope 流式 ASR (qwen-audio-3.0-asr-flash-streaming) -> 实时打印识别文本

相比 microphone.py，去掉了 Ray / Silero VAD / 自动重连等逻辑，只保留核心链路。

依赖安装:
    pip install pyaudio dashscope

运行:
    1. 设置环境变量(推荐，避免密钥写死在代码里):
         set DASHSCOPE_API_KEY=sk-xxx            (Windows CMD)
         $env:DASHSCOPE_API_KEY = "sk-xxx"       (PowerShell)
         export DASHSCOPE_API_KEY=sk-xxx         (Linux/macOS)
    2. 如果是专属/内部接入点(参考 microphone.py 第 18 行)，取消下面
       WS_URL 一行的注释并填上你的地址。
    3. python asr_min_demo.py
    对麦克风说话即可看到实时识别结果，按 Ctrl+C 结束。
"""

import os
import sys

import pyaudio
import dashscope
from dashscope.audio.asr import Recognition, RecognitionCallback, RecognitionResult

# ---------- 配置 ----------
# API Key 优先从环境变量读取；也可以直接写 dashscope.api_key = 'sk-xxx'
dashscope.api_key = os.environ.get('DASHSCOPE_API_KEY', '')

# 专属接入点示例(换成你自己的，microphone.py 里的 base_websocket_api_url 即此值)：
# dashscope.base_websocket_api_url = (
#     'wss://xxx.cn-beijing.maas.aliyuncs.com/api-ws/v1/inference'
# )

SAMPLE_RATE = 16000   # 支持 8000 / 16000
CHANNELS = 1          # 单声道
BLOCK_SIZE = 512      # PyAudio 每次读取的帧数(喂 ASR 无 512 限制，此处仅为读块大小)
FORMAT = 'pcm'        # int16 pcm


class Callback(RecognitionCallback):
    """把每一帧识别结果实时打印到终端。"""

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
            # \r 原地刷新：一句话在屏幕上逐渐"长出来"
            print('\r' + text, end='', flush=True)
            # 识别出一句完整的话(带结束标点)时换行
            if text[-1] in '。？！!?':
                print()
            # print(sentence)
            if sentence['sentence_end'] and text:
                print(f'[done]{text}')

def main():
    if not dashscope.api_key:
        sys.exit('请先设置环境变量 DASHSCOPE_API_KEY，例如: set DASHSCOPE_API_KEY=sk-xxx')

    # 1. 打开麦克风
    p = pyaudio.PyAudio()
    stream = p.open(format=pyaudio.paInt16,
                    channels=CHANNELS,
                    rate=SAMPLE_RATE,
                    input=True,
                    frames_per_buffer=BLOCK_SIZE)

    # 2. 启动流式识别
    recognition = Recognition(
        model='qwen-audio-3.0-asr-flash-streaming',
        format=FORMAT,
        sample_rate=SAMPLE_RATE,
        semantic_punctuation_enabled=True,  # 开启标点，便于判断一句话结束
        callback=Callback(),
    )
    recognition.start()

    # 3. 持续采集并送入 ASR，直到 Ctrl+C
    try:
        while True:
            data = stream.read(BLOCK_SIZE, exception_on_overflow=False)
            recognition.send_audio_frame(data)
    except KeyboardInterrupt:
        print('\n[Demo] 停止识别...')
    finally:
        recognition.stop()
        stream.stop_stream()
        stream.close()
        p.terminate()
        print('[Demo] 已退出')


if __name__ == '__main__':
    main()
