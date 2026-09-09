# -*- coding: utf-8 -*-
"""眼睛器官（esp32 端）：OV3660 拍照 → JPEG(base64) → 上行 sub/eye。
"""
try:
    import asyncio
except ImportError:
    import uasyncio as asyncio

import time

try:
    import ubinascii as binascii
except ImportError:
    import binascii

from .. import config

# ticks_ms 是 MicroPython API；CPython（PC 冒烟测试）没有，用 monotonic 兜底
try:
    _ticks_ms = time.ticks_ms
except AttributeError:
    _ticks_ms = lambda: int(time.monotonic() * 1000)

# 下行指令字：pub/eye 载荷 == b'photo' 才拍照（协议见文件头）
CMD_PHOTO = b'photo'


class CameraWorker:
    """眼睛：pub/eye 收 b'photo' → 拍一张 → 编码 → 推 sub/eye（一指令一图）。

    消费者型 worker（同 speak）：阻塞在入站 get() 上，stop_token 哨兵即退出。
    摄像头初始化失败不崩：保持存活，下一条指令再重试（固件缺模块 / FPC 没插好
    时只报错不拖垮其它器官）。
    """

    def __init__(self, queues, stop_token=None):
        self.queues = queues
        self.stop_token = stop_token
        self.cam = None                 # Camera 实例（None=未就绪，拍前重试）

    # ============================================================ 主循环
    async def run(self):
        print('[camera] 眼睛就绪：pub/eye 收到 b\'photo\' 拍一张推 sub/eye')
        await self._init_camera()
        while True:
            msg = await self.queues['pub/eye'].get()
            if self.stop_token is not None and msg is self.stop_token:
                break
            if msg.payload != CMD_PHOTO:
                print('[camera] 忽略 pub/eye 载荷 %r（协议目前只有 b\'photo\'）'
                      % msg.payload[:32])
                continue
            await self._snap()

    # ====================================================== 摄像头初始化
    async def _init_camera(self):
        """初始化 OV3660（Camera 类，显式引脚）。失败保持存活、下次指令重试。"""
        try:
            from camera import Camera, PixelFormat, FrameSize
        except ImportError:
            print('[camera] 无 camera 模块（固件需内置 esp32-camera，'
                  '见 docs/烧录指南.md）')
            self.cam = None
            return
        try:
            self.cam = Camera(
                pixel_format=PixelFormat.RGB565,
                frame_size=getattr(FrameSize, config.CAM_FRAME_SIZE),
                **config.CAM_PINS,
            )
            name = '?'
            try:
                name = self.cam.get_sensor_name()
            except Exception:
                pass
            for _ in range(5):          # 丢几帧让自动曝光/白平衡稳定
                try:
                    self.cam.capture()
                except Exception:
                    pass
                await asyncio.sleep(0.05)
            print('[camera] 摄像头就绪: %s (%s %dx%d)'
                  % (name, config.CAM_FRAME_SIZE, config.CAM_W, config.CAM_H))
        except Exception as e:
            print('[camera] 摄像头初始化失败（检查 FPC 排线方向/供电）: %s' % e)
            try:
                self.cam.deinit()
            except Exception:
                pass
            self.cam = None

    # ============================================ 拍照 → 编码 → 出站入队
    async def _snap(self):
        """拍一张并推入 sub/eye 队列；失败/未就绪返回 None（不抛出、保持存活）"""
        if self.cam is None:
            await self._init_camera()       # 首次/失败后按指令重试初始化
        if self.cam is None:
            print('[camera] 摄像头未就绪，本次拍照放弃（固件缺模块或 FPC 没插好）')
            return None

        t0 = _ticks_ms()
        try:
            # ---- 暖帧：连拍 SNAP_WARM_FRAMES 帧丢弃，AE/AWB 收敛后取正式帧 ----
            # demo 画面清楚的关键是连续取帧、曝光一直在收敛；每次拍照前快拍几帧
            # 预热，照片就是清楚、曝光正确的"当下"画面（参数见 config.SNAP_*）。
            for _ in range(config.SNAP_WARM_FRAMES):
                try:
                    self.cam.capture()          # 暖帧，丢弃
                except Exception as e:
                    print('[camera] 暖帧取帧失败（继续）: %s' % e)
                await asyncio.sleep(config.SNAP_WARM_STEP_MS / 1000.0)
            frame = self.cam.capture()          # 曝光稳定后的正式帧 = 当下画面
            import jpeg
            enc = jpeg.Encoder(width=config.CAM_W, height=config.CAM_H,
                               pixel_format=config.CAM_PIXEL_FMT,
                               quality=config.JPEG_QUALITY)
            jpg = bytes(enc.encode(frame))      # JPEG bytes
        except Exception as e:
            print('[camera] 拍照失败: %s' % e)
            return None
        if not jpg:
            print('[camera] 拍照返回空数据')
            return None

        # JPEG -> base64（ubinascii/binascii 跨平台）
        b64 = binascii.b2a_base64(jpg).decode('utf-8', 'ignore').strip()

        # JSON 信封：字段固定顺序手拼（值都来自本机、无引号/转义风险）
        t = time.localtime()
        ts = '%04d-%02d-%02d %02d:%02d:%02d' % (t[0], t[1], t[2], t[3], t[4], t[5])
        payload = ('{"type":"photo","time":"%s","size":%d,"width":%d,'
                   '"height":%d,"data":"%s"}'
                   % (ts, len(jpg), config.CAM_W, config.CAM_H, b64)).encode('utf-8')

        # 上行出站队列（满则丢最旧，保新鲜；专职发送任务负责发布）
        self.queues['sub/eye'].put_nowait(payload)
        print('[camera] 已拍照并入队: %s, jpeg=%dB -> 载荷%dB, 耗时%dms'
              % (ts, len(jpg), len(payload), _ticks_ms() - t0))
        return payload
