"""文本→语音：消费内部 tts 队列的文本，流式合成 PCM 转发到 pub/speak。

一句一个会话，句末由预热线程在后台为下一句建连；出声前给耳朵发 stop、说完发 start 防回音。
"""

import array
import base64
import threading
import time

import dashscope
from dashscope.audio.qwen_tts_realtime import (
    QwenTtsRealtime, QwenTtsRealtimeCallback, AudioFormat,
)
from queue import Queue

from ..config import (DASHSCOPE_API_KEY, EAR_START, EAR_STOP, QUEUE_EAR_CTRL,
                      QUEUE_SPEAK_OUT, QUEUE_TTS, TTS_CONNECT_TIMEOUT, TTS_MODEL,
                      TTS_SENTENCE_TIMEOUT, TTS_SPEED, TTS_VOICE, TTS_VOLUME_DIV,
                      TTS_WS_URL)

dashscope.api_key = DASHSCOPE_API_KEY


def _attenuate(pcm: bytes, div: int) -> bytes:
    """int16 PCM 每样本右移 div 位（数字衰减）。"""
    if div <= 1:
        return pcm
    a = array.array('h', pcm)          # 'h' = int16，本机小端与 PCM 一致
    for i in range(len(a)):
        a[i] >>= div
    return a.tobytes()


class Callback(QwenTtsRealtimeCallback):
    def __init__(self, worker):
        self.worker = worker
        self.used = False                        # 已发过文本（一句一会话，防复用）
        self.sent_bytes = 0                      # 本句已转发的 PCM 字节数
        self.open_at = None                      # 连接建立时刻
        self.first_audio_at = None               # 本句第一段 PCM 的时刻
        self.complete_event = threading.Event()  # 本句合成完毕（session.finished）
        self.open_event = threading.Event()      # 连接建立（on_open）
        self.closed_event = threading.Event()    # 连接关闭（on_close）

    def on_open(self):
        self.open_at = time.perf_counter()
        self.open_event.set()

    def on_event(self, response):
        try:
            type_ = response.get('type')
            if type_ == 'response.audio.delta':
                if self.first_audio_at is None:
                    self.first_audio_at = time.perf_counter()
                pcm = _attenuate(base64.b64decode(response['delta']),
                                 TTS_VOLUME_DIV)
                self.worker.queues[QUEUE_SPEAK_OUT].put(pcm)
                self.sent_bytes += len(pcm)
            elif type_ == 'session.finished':
                self.complete_event.set()
        except Exception as e:
            print('[TTS] 处理事件出错:', e, flush=True)

    def on_close(self, close_status_code, close_msg):
        self.closed_event.set()


class SpeakWorker:
    def __init__(self, queues: dict[str, Queue], stop_token=None):
        self.queues = queues
        self.stop_token = stop_token
        self._lock = threading.Lock()
        self._session = None                 # 当前 QwenTtsRealtime
        self._cb = None                      # 当前 Callback
        self._ready = threading.Event()      # 已有一条可用连接
        self._warming = False                # 预热线程是否在跑
        self._dying = False                  # close() 后不再建连

    def run(self):
        missing = [k for k in (QUEUE_TTS, QUEUE_SPEAK_OUT, QUEUE_EAR_CTRL)
                   if k not in self.queues]
        if missing:
            print('[TTS] 缺少队列 %s:请检查 config.py 的 SUB/PUB_TOPICS'
                  % missing, flush=True)
            return
        if not dashscope.api_key:
            print('[TTS] 警告: 未设置 DASHSCOPE_API_KEY,合成将失败', flush=True)
        print('[TTS] SpeakWorker 已启动,等待 %s 队列文本...' % QUEUE_TTS,
              flush=True)
        self._start_warm()   # 先预热第一句的连接
        try:
            while True:
                item = self.queues[QUEUE_TTS].get()
                if self.stop_token is not None and item is self.stop_token:
                    break
                text = item
                if not text:
                    continue
                self._speak(text)   # 阻塞到本句转发完，内部兜底不外抛
        finally:
            self.close()

    def close(self):
        """停掉预热并释放当前会话（幂等）。"""
        self._dying = True
        with self._lock:
            self._drop_locked()

    def _drop_locked(self):
        """丢弃当前会话；调用方须已持锁。"""
        self._ready.clear()
        tts, self._session = self._session, None
        self._cb = None
        if tts is not None:
            try:
                tts.close()
            except Exception:
                pass

    def _open_locked(self):
        """新建一条会话并等 on_open；调用方须已持锁。"""
        self._drop_locked()
        cb = Callback(self)
        tts = QwenTtsRealtime(model=TTS_MODEL, callback=cb, url=TTS_WS_URL)
        try:
            tts.connect()
            tts.update_session(voice=TTS_VOICE,
                               response_format=AudioFormat.PCM_24000HZ_MONO_16BIT,
                               mode='server_commit',
                               speech_rate=TTS_SPEED)
            if not cb.open_event.wait(timeout=TTS_CONNECT_TIMEOUT):
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
        """还能接新句子：已连接、未断开、且从未发过文本。"""
        return (self._session is not None and self._cb is not None
                and self._cb.open_event.is_set()
                and not self._cb.closed_event.is_set()
                and not self._cb.used)

    def _start_warm(self):
        """后台为下一句建好新连接（替换上一句用过的）。"""
        if self._dying or self._warming:
            return
        self._warming = True

        def _run():
            try:
                with self._lock:
                    if not self._dying:
                        self._open_locked()
            except Exception as e:
                print('[TTS] 预热连接失败(下句将现场重连): %s' % e, flush=True)
            finally:
                self._warming = False

        threading.Thread(target=_run, daemon=True, name='tts-prewarm').start()

    def _ready_session(self):
        """返回可用的 Callback；必要时等预热或现场建连。"""
        if self._usable():
            return self._cb
        if self._warming:
            # 不持锁等，否则预热线程拿不到锁
            self._ready.wait(timeout=TTS_CONNECT_TIMEOUT)
        with self._lock:
            if not self._usable():
                self._open_locked()      # 预热没赶上/失败：现场建连
        return self._cb

    def _speak(self, text):
        """合成一句并流式转发；失败只打印，不外抛。"""
        t0 = time.perf_counter()
        print('[TTS] 说: %s' % text[:60], flush=True)

        try:
            cb = self._ready_session()
        except Exception as e:
            print('[TTS] 建连失败,本句放弃: %s' % e, flush=True)
            self._start_warm()
            return

        self.queues[QUEUE_EAR_CTRL].put(EAR_STOP)   # 出声前停采，防回音
        try:
            ok = self._send_wait(cb, text)
            if not ok:                              # 断线就重连补发一次
                try:
                    with self._lock:
                        self._open_locked()
                    cb = self._cb
                    ok = self._send_wait(cb, text)
                except Exception as e:
                    print('[TTS] 重连失败,本句放弃: %s' % e, flush=True)
                    ok = False
        finally:
            self.queues[QUEUE_EAR_CTRL].put(EAR_START)

        if cb is not None and cb.open_at is not None:
            first = (cb.first_audio_at - t0) if cb.first_audio_at is not None \
                else float('nan')
            detail = '' if not ok else ' | %d 字节 PCM' % cb.sent_bytes
            print('[TTS] 建连 %.2fs | 首包 %.2fs | 整句 %.1fs%s' % (
                max(0.0, cb.open_at - t0), first,
                time.perf_counter() - t0, detail), flush=True)
        self._start_warm()

    def _send_wait(self, cb, text):
        """发文本并阻塞等合成完；失败返回 False。"""
        cb.complete_event.clear()
        cb.first_audio_at = None
        cb.sent_bytes = 0
        cb.used = True   # 发过文本的会话不复用
        try:
            self._session.append_text(text)
            self._session.finish()
        except Exception as e:
            print('[TTS] 发送失败: %s' % e, flush=True)
            return False
        waited = 0.0
        while not cb.complete_event.is_set():
            if cb.closed_event.is_set():
                print('[TTS] 合成中连接断开', flush=True)
                return False
            if waited >= TTS_SENTENCE_TIMEOUT:
                print('[TTS] 合成超时(%.0fs)' % TTS_SENTENCE_TIMEOUT, flush=True)
                return False
            cb.complete_event.wait(timeout=0.2)
            waited += 0.2
        return True
