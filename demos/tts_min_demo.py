"""
TTS Demo —— 后台预热版(针对"逐句 0.5s 建连"实测优化)
=====================================================
控制台输入文本 -> DashScope 流式 TTS (qwen3-tts-flash-realtime) -> 声卡实时播放

实测定位(你的机器上):
    建连 0.50~0.54s | 首包 0.71~0.77s | 整句 ~1.0s
  首包 0.7s 里,建连占了 ~0.5s,服务器合成首 token 只有 ~0.2s;
  而且每句都重新付这 0.5s(第二句、第三句的建连没有变小)。

本版的做法(仍无 Ray / 队列 / 声卡锁,单文件、天然串行):
  * 后台预热:程序启动后、以及每句说完,立刻在一个 daemon 线程里为
    "下一句"把 ws 连接建好(connect + update_session)。
    你打字/看屏幕的时段(通常 >0.5s)连接就已就绪,回车后直接 append 文本,
    不再当场等建连 —— 预热生效时每句"建连"应打印为 0.00s。
  * 仍是一句一个会话(connect -> append -> finish),与你已验证能跑通的
    调用链完全一致,不赌服务器是否允许同一条连接连续合成。
  * 自动兜底:发送失败 / 中途断线 / 空闲被服务器断开时,自动重连并
    补发一次;建连失败(如断网)则本句放弃并提示,回车可再试。
    任何情况都不会崩,也不会永久卡住(每步都有超时上限)。

仍无法省的延迟(属于服务器侧):
  首包里的 ~0.2s 合成时间(文本越长通常越高);想再低只能换
  更近/专属的接入点(WS_URL)或缩短单句文本。

依赖安装:
    pip install pyaudio dashscope

运行:
    1. 设置环境变量(推荐,避免密钥写死在代码里):
         set DASHSCOPE_API_KEY=sk-xxx            (Windows CMD)
         $env:DASHSCOPE_API_KEY = "sk-xxx"       (PowerShell)
         export DASHSCOPE_API_KEY=sk-xxx         (Linux/macOS)
    2. 快速试一句(念完即退出):
         python demos/tts_min_demo.py 你好,我是测试语音
    3. 交互模式(逐句念,Ctrl+C 结束):
         python demos/tts_min_demo.py
       在提示符后输入一行文本回车,即可听到实时合成播放。
       对照方法:连念三句,看"建连"是否变成 0.00s。
"""

import os
import sys
import time
import base64
import threading

import pyaudio
import dashscope
from dashscope.audio.qwen_tts_realtime import (
    QwenTtsRealtime, QwenTtsRealtimeCallback, AudioFormat,
)

# ---------- 配置 ----------
# API Key 优先从环境变量读取;也可以直接写 dashscope.api_key = 'sk-xxx'
dashscope.api_key = os.environ.get('DASHSCOPE_API_KEY', '')

# 专属接入点示例(换成你自己的,与 Speaker 里 QwenTtsRealtime(url=...) 同义):
# WS_URL = 'wss://xxx.cn-beijing.maas.aliyuncs.com/api-ws/v1/realtime'
WS_URL = 'wss://dashscope.aliyuncs.com/api-ws/v1/realtime'

MODEL = 'qwen3-tts-flash-realtime'
VOICE = 'Chelsie'        # 音色
TTS_SPEED = 1.2          # 语速倍率:范围 0.5~2.0(1.0 为正常语速)
SAMPLE_RATE = 24000      # 该模型输出的 PCM 采样率(单声道 int16)
FRAMES_PER_BUFFER = 960  # 播放缓冲帧数(≈40ms@24kHz):过小易爆音,过大增延迟

CONNECT_TIMEOUT = 6.0    # 建连(含后台预热)最长等待秒数
SENTENCE_TIMEOUT = 30.0  # 单句合成/播放超时秒数,防网络异常导致永久卡住


class Player:
    """进程级唯一声卡:启动时打开一次、全程复用,退出时关闭。

    原来每句话都在回调里新建 pyaudio.PyAudio():首句要额外付设备初始化,
    之后每句也重复付,逐句开关声卡还容易爆音。提出来复用后这笔开销只付一次。
    """

    def __init__(self):
        self._pa = pyaudio.PyAudio()
        self._stream = self._pa.open(format=pyaudio.paInt16,
                                     channels=1,
                                     rate=SAMPLE_RATE,
                                     output=True,
                                     frames_per_buffer=FRAMES_PER_BUFFER)
        self._stream.start_stream()

    def write(self, data):
        self._stream.write(data)

    def close(self):
        try:
            self._stream.stop_stream()
            self._stream.close()
        finally:
            self._pa.terminate()


class Callback(QwenTtsRealtimeCallback):
    """一次 TTS 会话的回调:把流式 PCM 交给共享声卡实时播出。

    只负责收流写数据 + 记录时间点与连接状态事件(供主线程等待/判断),
    不持有 pyaudio(由 Player 统一管理)。
    """

    def __init__(self, player):
        self.player = player
        self.complete_event = threading.Event()  # 本句合成完毕(session.finished)
        self.open_event = threading.Event()      # 连接建立(on_open)
        self.closed_event = threading.Event()    # 连接关闭(on_close,任何一方)
        self.open_at = None                      # 连接建立时刻
        self.first_audio_at = None               # 本句收到第一段 PCM 的时刻

    def on_open(self):
        self.open_at = time.perf_counter()
        self.open_event.set()

    def on_event(self, response):
        try:
            type_ = response.get('type')
            if type_ == 'response.audio.delta':
                if self.first_audio_at is None:
                    self.first_audio_at = time.perf_counter()
                self.player.write(base64.b64decode(response['delta']))
            elif type_ == 'session.finished':
                self.complete_event.set()
            # 'session.created' / 'response.done' 等事件与本 demo 无关,忽略
        except Exception as e:
            print('[TTS] 处理事件出错:', e, flush=True)

    def on_close(self, close_status_code, close_msg):
        self.closed_event.set()


class TtsEngine:
    """预热式 TTS 引擎:连接在后台提前备好,回车后只付合成首包的时间。

    线程模型:预热工作在一个 daemon 线程里做,与主线程(input/say)不抢
    声卡(声卡写只在 SDK 回调线程发生,且同一时刻只有一个会话在播)。
    仍保持"一句一个会话",与已验证的调用链一致;只是把建连从
    "回车之后"挪到"上一句之后/启动时"。
    """

    def __init__(self, player):
        self.player = player
        self._lock = threading.Lock()
        self._session = None                 # 当前 QwenTtsRealtime
        self._cb = None                      # 当前 Callback
        self._ready = threading.Event()      # 已有一个可用连接
        self._warming = False                # 预热线程是否在跑(避免重复预热)
        self._dying = False                  # close() 后不再建连

    # ------------------------------------------------------- 建连/关连
    def _drop_locked(self):
        """丢弃当前会话(若有)。调用方须已持锁。"""
        self._ready.clear()
        tts, self._session = self._session, None
        self._cb = None
        if tts is not None:
            try:
                tts.close()
            except Exception:
                pass

    def _open_locked(self):
        """新建一条会话并等它 on_open。调用方须已持锁。"""
        self._drop_locked()
        cb = Callback(self.player)
        tts = QwenTtsRealtime(model=MODEL, callback=cb, url=WS_URL)
        try:
            tts.connect()
            tts.update_session(voice=VOICE,
                               response_format=AudioFormat.PCM_24000HZ_MONO_16BIT,
                               mode='server_commit',
                               speech_rate=TTS_SPEED)
            if not cb.open_event.wait(timeout=CONNECT_TIMEOUT):
                raise RuntimeError('等待 on_open 超时')
        except Exception:
            try:
                tts.close()
            except Exception:
                pass
            raise
        self._session, self._cb = tts, cb
        self._ready.set()

    def _usable(self):
        return (self._session is not None and self._cb is not None
                and self._cb.open_event.is_set()
                and not self._cb.closed_event.is_set())

    def _start_warm(self):
        """启动/句末调用:后台为下一句建好新连接(替换上一句用过的)。

        预热在 daemon 线程进行,期间主线程照常停在 input() 等输入,
        用户打字的时间就把 ~0.5s 建连消化掉了。
        """
        if self._dying or self._warming:
            return
        self._warming = True

        def _run():
            try:
                with self._lock:
                    if not self._dying:
                        self._open_locked()
            except Exception as e:
                print('[TTS] 预热连接失败(回车时将现场重连): %s' % e, flush=True)
            finally:
                self._warming = False

        threading.Thread(target=_run, daemon=True, name='tts-prewarm').start()

    # ------------------------------------------------------- 念一句
    def say(self, text):
        """念一句:优先用后台已备好的连接,没有就现场建;阻塞到播完。

        返回 True=正常播完,False=失败(已尽量重试过一次)。
        """
        t0 = time.perf_counter()

        # 1) 取一条可用连接:有预热好的直接用;预热还没好就等它;都没有就现场建。
        #    建连本身失败(断网/服务不可达)不往上抛:打印后本句放弃,回车可再试
        try:
            cb = self._ready_session()
        except Exception as e:
            print('[TTS] 建连失败,本句放弃(可直接回车再试): %s' % e, flush=True)
            self._start_warm()
            return False

        # 2) 发送 + 等待播完;失败/断线自动重连补发一次
        ok = self._send_wait(cb, text)
        if not ok:
            try:
                with self._lock:
                    self._open_locked()
                cb = self._cb
                ok = self._send_wait(cb, text)
            except Exception as e:
                print('[TTS] 重连失败,本句放弃: %s' % e, flush=True)
                ok = False

        # 3) 计时 + 为下一句预热(返回 input 之前先点火,后台慢慢建)
        if cb is not None and cb.open_at is not None:
            first = (cb.first_audio_at - t0) if cb.first_audio_at is not None \
                else float('nan')
            print('[TTS] 建连 %.2fs | 首包 %.2fs | 整句 %.1fs' % (
                max(0.0, cb.open_at - t0), first,
                time.perf_counter() - t0), flush=True)
        self._start_warm()
        return ok

    def _ready_session(self):
        """返回当前会话的 Callback(连接已可用);必要时等预热或现场建连。"""
        if self._usable():
            return self._cb
        if self._warming:
            # 预热线程正在建连:等它(不持锁,否则预热线程拿不到锁)
            self._ready.wait(timeout=CONNECT_TIMEOUT)
        with self._lock:
            if not self._usable():
                self._open_locked()      # 预热没赶上/失败:现场建连兜底
        return self._cb

    def _send_wait(self, cb, text):
        """把文本发给当前会话并阻塞等它播完;失败返回 False。"""
        cb.complete_event.clear()
        cb.first_audio_at = None
        try:
            self._session.append_text(text)
            self._session.finish()
        except Exception as e:
            print('[TTS] 发送失败: %s' % e, flush=True)
            return False
        # 阻塞等本句播完;连接中途断开立刻返回 False 以便上层重连重发
        waited = 0.0
        while not cb.complete_event.is_set():
            if cb.closed_event.is_set():
                print('[TTS] 播放中连接断开', flush=True)
                return False
            if waited >= SENTENCE_TIMEOUT:
                print('[TTS] 播放超时(%.0fs)' % SENTENCE_TIMEOUT, flush=True)
                return False
            cb.complete_event.wait(timeout=0.2)
            waited += 0.2
        return True

    def close(self):
        """停掉预热并释放当前会话(幂等)。"""
        self._dying = True
        with self._lock:
            self._drop_locked()


def main():
    if not dashscope.api_key:
        sys.exit('请先设置环境变量 DASHSCOPE_API_KEY,例如: set DASHSCOPE_API_KEY=sk-xxx')

    player = Player()   # 声卡提前打开:首句的关键路径不再含设备初始化
    engine = TtsEngine(player)
    try:
        # 命令行直接带文本:念完即退出,方便快速验证整条链路
        if len(sys.argv) > 1:
            text = ' '.join(sys.argv[1:])
            print('[TTS] 念:', text, flush=True)
            engine.say(text)
            print('[TTS] 播放完毕', flush=True)
            return

        # 交互模式:输入一行念一行
        print('[TTS] 逐句朗读模式(连接在后台预热,回车后只等首包),'
              '直接回车跳过,Ctrl+C 退出。', flush=True)
        engine._start_warm()   # 预热第一句:等你输入完,连接早已就绪
        while True:
            try:
                text = input('> ').strip()
            except (EOFError, KeyboardInterrupt):
                print('\n[TTS] 已退出', flush=True)
                break
            if not text:
                continue
            try:
                engine.say(text)
            except KeyboardInterrupt:
                # 播放中按 Ctrl+C:直接退出(engine/player 由 finally 清理)
                print('\n[TTS] 已退出', flush=True)
                break
            except Exception as e:
                # 兜底:任何未预期异常都不让 REPL 崩掉,打印后继续等下一句
                print('[TTS] 本句异常已跳过,可继续输入: %s' % e, flush=True)
    finally:
        engine.close()


if __name__ == '__main__':
    main()
