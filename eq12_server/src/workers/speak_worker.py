"""
SpeakWorker —— 文本→语音(预热版):把 tts 队列文本合成 PCM,转发到 pub/speak 出站队列
=====================================================================================

数据流位置(与 EarWorker 对称):
    sub/ear 原始音频 → EarWorker(ASR) → queues['asr']
        → (大脑/上游逻辑) 生成回复文本 → queues['tts']   ← 本 worker 在此消费
    SpeakWorker(流式 TTS) → queues['pub/speak']
        → 专职发送线程 → MQTT pub/speak → ESP32(声卡实时播放)

本 worker 不碰本地声卡(pyaudio):每收到一段流式 PCM,原样、按序塞进出站
队列 pub/speak,由框架的专职发送线程发布到 broker;真正"出声"的是订阅
pub/speak 主题的 ESP32 端。

后台预热(照搬 demos/tts_min_demo.py 的连接复用机制):
    启动时、以及每句说完后,立刻在一个 daemon 线程里为"下一句"把 ws 连接
    建好(connect + update_session)。worker 阻塞在 tts 队列等文本的时段
    (大脑思考/上游产生下句文本的间隔,通常 > 0.5s)连接就已就绪,文本一到
    直接 append,不再当场等建连 —— 预热生效时日志里"建连"应显示 0.00s。

仍是一句一个会话(与 demo 一致):
    发送过文本的会话立刻标记"已用",绝不复用给下一句(used 标记挡住
    "预热线程还没来得及替换"的竞态窗口),不赌服务器是否允许同一条连接
    连续合成;下一句由预热线程换上的新连接服务。预热没赶上/失败时自动
    现场建连兜底,任何情况都不会卡死(每步都有超时上限)。

下行音频格式契约(ESP32 按此配置解码播放):
    PCM int16 / 单声道 / 24000Hz —— 该 TTS 模型的固定输出;
    注意 sub/ear 上行的 ASR 是 16000Hz,两个方向采样率不同。

回音控制(防 mic 收到自己喇叭的声音形成自答循环):
    每句出声前,本 worker 往出站队列 pub/ear 推 b'stop'(ESP32 耳朵停采);
    本句播完或放弃后(含失败/超时路径)推 b'start' 恢复采集 —— 用
    try/finally 保证任何路径都会发 start,耳朵不会永久静音。协议:
        pub/ear  payload = b'stop'  / b'start'(控制耳朵采集)
        pub/speak payload = PCM 流(播音)
    注:stop 与音频分属两个主题,到达 ESP32 的顺序不严格;建议 ESP32 端
    收到 stop 前已到达的 speak 音频先缓存,待 start 后再播(或收到 stop
    后清空未播缓冲)。

接线要求:
    需在 src/config.py 的 PUB_TOPICS 里加入 pub/speak,出站队列与专职发送
    线程才会存在(run() 启动时会自检,缺队列会给出提示)。

停机说明:
    MainLoop.stop() 只向 pub/*、sub/* 前缀队列投 _STOP,内部 asr/tts 队列
    不投(避免哨兵被下游 worker 当成业务数据),因此本 worker 平时收不到哨兵
    —— daemon 线程随进程退出结束,close() 幂等、随时可调。若需线程级优雅
    退出,要在 MainLoop.stop() 里另行通知(如也给 tts 队列投 _STOP,消费处
    已兼容识别)。

依赖:
    pip install dashscope
    set DASHSCOPE_API_KEY=sk-xxx
"""

import os
import base64
import threading
import time

import dashscope
from dashscope.audio.qwen_tts_realtime import (
    QwenTtsRealtime, QwenTtsRealtimeCallback, AudioFormat,
)
from queue import Queue

# ---------- 配置 ----------
# API Key 优先从环境变量读取;也可以直接写 dashscope.api_key = 'sk-xxx'
dashscope.api_key = os.environ.get('DASHSCOPE_API_KEY', '')

SPEAK_QUEUE = 'tts'         # 消费:内部流水线队列,里面是要说的文本
OUTPUT_QUEUE = 'pub/speak'  # 产出:出站队列 → 专职发送线程 → MQTT pub/speak → ESP32 播放
EAR_QUEUE = 'pub/ear'       # 出站队列:控制 ESP32 耳朵采集启停(回声抑制)
EAR_STOP = b'stop'          # 出声前推送:耳朵停采,防 mic 收到自己的声音
EAR_START = b'start'        # 本句播完/放弃后推送:耳朵恢复采集
# WS_URL = 'wss://xxx.cn-beijing.maas.aliyuncs.com/api-ws/v1/realtime'  # 专属接入点示例
WS_URL = 'wss://dashscope.aliyuncs.com/api-ws/v1/realtime'

MODEL = 'qwen3-tts-flash-realtime'
VOICE = 'Chelsie'        # 音色
TTS_SPEED = 1.2          # 语速倍率:范围 0.5~2.0(1.0 为正常语速)

CONNECT_TIMEOUT = 6.0    # 建连(含后台预热)最长等待秒数
SENTENCE_TIMEOUT = 30.0  # 单句合成超时秒数,防网络异常导致永久卡住


class Callback(QwenTtsRealtimeCallback):
    """一次 TTS 会话的回调:把流式 PCM 逐段转发给出站队列 pub/speak。

    只负责收流转发 + 记录时间点/连接状态事件(供主循环等待/判断),
    不持有任何音频设备。
    """

    def __init__(self, worker):
        self.worker = worker
        self.used = False                        # 是否已发送过文本(一句一会话防复用)
        self.sent_bytes = 0                      # 本句已转发的 PCM 字节数
        self.open_at = None                      # 连接建立时刻
        self.first_audio_at = None               # 本句收到第一段 PCM 的时刻
        self.complete_event = threading.Event()  # 本句合成完毕(session.finished)
        self.open_event = threading.Event()      # 连接建立(on_open)
        self.closed_event = threading.Event()    # 连接关闭(on_close,任何一方)

    def on_open(self):
        self.open_at = time.perf_counter()
        self.open_event.set()

    def on_event(self, response):
        try:
            type_ = response.get('type')
            if type_ == 'response.audio.delta':
                if self.first_audio_at is None:
                    self.first_audio_at = time.perf_counter()
                pcm = base64.b64decode(response['delta'])
                # 放进 pub/speak 出站队列,专职发送线程会发布给 ESP32
                self.worker.queues[OUTPUT_QUEUE].put(pcm)
                self.sent_bytes += len(pcm)
            elif type_ == 'session.finished':
                self.complete_event.set()
            # 'session.created' / 'response.done' 等事件与本 worker 无关,忽略
        except Exception as e:
            print('[TTS] 处理事件出错:', e, flush=True)

    def on_close(self, close_status_code, close_msg):
        self.closed_event.set()


class SpeakWorker:
    """消费内部 tts 队列的文本,逐句流式合成并把 PCM 转发到 pub/speak。

    连接管理照搬 demo 的 TtsEngine:预热线程在后台提前为下一句建好连接,
    文本到达时直接取用(当场不再等建连);仍一句一会话,不赌服务器允许
    同一条连接连续合成。

    stop_token 是主循环停机时投进 pub/*、sub/* 队列的 _STOP 哨兵对象;
    run() get() 到它即退出(不把它当业务文本),用于优雅停机。
    """

    def __init__(self, queues: dict[str, Queue], stop_token=None):
        self.queues = queues
        self.stop_token = stop_token
        self._lock = threading.Lock()
        self._session = None                 # 当前 QwenTtsRealtime
        self._cb = None                      # 当前 Callback
        self._ready = threading.Event()      # 已有一条可用连接
        self._warming = False                # 预热线程是否在跑(避免重复预热)
        self._dying = False                  # close() 后不再建连

    # ------------------------------------------------------- 主循环
    def run(self):
        # 自检:队列必须存在,否则没有任何东西会真的发到 MQTT
        missing = [k for k in (SPEAK_QUEUE, OUTPUT_QUEUE, EAR_QUEUE)
                   if k not in self.queues]
        if missing:
            print('[TTS] 缺少队列 %s:请检查 config.py 的 SUB/PUB_TOPICS'
                  % missing, flush=True)
            return
        if not dashscope.api_key:
            print('[TTS] 警告: 未设置 DASHSCOPE_API_KEY,合成将失败', flush=True)
        print('[TTS] SpeakWorker 已启动,等待 %s 队列文本...' % SPEAK_QUEUE,
              flush=True)
        self._start_warm()   # 先预热第一句的连接
        try:
            while True:
                item = self.queues[SPEAK_QUEUE].get()
                if self.stop_token is not None and item is self.stop_token:
                    break
                text = item
                if not text:
                    continue
                self._speak(text)   # 阻塞到本句转发完毕;内部全兜底,不外抛
        finally:
            self.close()

    def close(self):
        """停掉预热并释放当前会话(幂等,可从任意线程调用)。"""
        self._dying = True
        with self._lock:
            self._drop_locked()

    # ------------------------------------------------------- 建连/关连(移植自 demo)
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
        cb = Callback(self)
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
        """当前会话是否还能接新句子:已连接、未断开、且从未发送过文本。"""
        return (self._session is not None and self._cb is not None
                and self._cb.open_event.is_set()
                and not self._cb.closed_event.is_set()
                and not self._cb.used)

    def _start_warm(self):
        """启动/句末调用:后台为下一句建好新连接(替换上一句用过的)。

        预热在 daemon 线程进行,期间主循环照常阻塞在 tts 队列等文本,
        上游产生下句文本的间隔就把 ~0.5s 建连消化掉了。
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
                print('[TTS] 预热连接失败(下句将现场重连): %s' % e, flush=True)
            finally:
                self._warming = False

        threading.Thread(target=_run, daemon=True, name='tts-prewarm').start()

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

    # ------------------------------------------------------- 说一句
    def _speak(self, text):
        """合成一句文本,流式转发到 pub/speak;任何失败只打印,不外抛。

        与 demo 的 say() 同构:优先用后台预热好的连接,没有就现场建;
        失败/断线自动重连补发一次;句末点火为下一句预热。
        """
        t0 = time.perf_counter()
        print('[TTS] 说: %s' % text[:60], flush=True)

        # 1) 取一条可用连接:预热好的直接用;预热没赶上就等;都没有就现场建。
        #    建连失败(断网/服务不可达)不往上抛:本句放弃,等下一句再试
        try:
            cb = self._ready_session()
        except Exception as e:
            print('[TTS] 建连失败,本句放弃: %s' % e, flush=True)
            self._start_warm()
            return

        # 2) 出声前让耳朵停采(防回音);整句处理完(成功/失败/重连)再恢复。
        #    try/finally 保证任何路径都发 start,耳朵不会永久静音。
        self.queues[EAR_QUEUE].put(EAR_STOP)
        try:
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
        finally:
            self.queues[EAR_QUEUE].put(EAR_START)

        # 3) 计时 + 为下一句预热(回到等文本之前先点火,后台慢慢建)
        if cb is not None and cb.open_at is not None:
            first = (cb.first_audio_at - t0) if cb.first_audio_at is not None \
                else float('nan')
            detail = '' if not ok else ' | %d 字节 PCM' % cb.sent_bytes
            print('[TTS] 建连 %.2fs | 首包 %.2fs | 整句 %.1fs%s' % (
                max(0.0, cb.open_at - t0), first,
                time.perf_counter() - t0, detail), flush=True)
        self._start_warm()

    def _send_wait(self, cb, text):
        """把文本发给当前会话并阻塞等它合成完;失败返回 False。"""
        cb.complete_event.clear()
        cb.first_audio_at = None
        cb.sent_bytes = 0
        cb.used = True   # 一句一会话:发过文本的会话绝不复用给下一句
        try:
            self._session.append_text(text)
            self._session.finish()
        except Exception as e:
            print('[TTS] 发送失败: %s' % e, flush=True)
            return False
        # 阻塞等本句合成完;连接中途断开立刻返回 False 以便上层重连重发
        waited = 0.0
        while not cb.complete_event.is_set():
            if cb.closed_event.is_set():
                print('[TTS] 合成中连接断开', flush=True)
                return False
            if waited >= SENTENCE_TIMEOUT:
                print('[TTS] 合成超时(%.0fs)' % SENTENCE_TIMEOUT, flush=True)
                return False
            cb.complete_event.wait(timeout=0.2)
            waited += 0.2
        return True
