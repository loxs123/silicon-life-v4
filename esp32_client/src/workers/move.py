# -*- coding: utf-8 -*-
"""腿器官（esp32 端）：pub/leg 运动指令 → PCA9685 云台舵机 + DRV8833 电机。

与 eq12_server 的对应关系：
    eq12 的 BrainWorker（或其它角色）下发运动指令 pub/leg（下行）；本 worker
    收到一条做一条，**一条做完才做下一条**（动作串行，不叠指令）。

指令载荷 = 文本（UTF-8，裸 bytes），格式与 v3 src/actors/move.py 完全一致：
    "forward,50"           前进 50%（默认 1.5s 自动停）
    "forward,50,3"         前进 3 秒（第 3 参 = 持续秒数，支持 "3"/"1.5s"/"800ms"/"2秒"）
    "back,40"              后退 40%
    "left,30"              原地左转 30%（默认 1.0s）
    "right,30,2"           原地右转 2 秒
    "pan,90"               云台水平 → 90°（机械限幅 60~120，见 config.MOVE）
    "tilt,45"              云台俯仰 → 45°（机械限幅 45~135）
    "stop"                 电机立即停止
    "center"               云台回中(90/90) + 电机停
    也接受旧协议前缀与空格分隔："[MOVE]:pan,90" / "forward 50 2"（_parse 容错）。

执行语义（与 ear/speak/camera 的区别）：
    ear 常开流、eye 按指令拍一张即回；**leg 是"串行动作执行器"**——指令在
    pub/leg 队列里排队（config.LEG_Q_MAX=64，EQ12 可一次下发一串动作），
    worker 收一条做一条：舵机动作立即到位；电机动作跑完指定时长自动停，
    再取下一条。停机/异常路径用 finally 保证电机一定停（不会"一直冲"）。

所有参数（通道/引脚/限幅/方向校准/默认时长）在 src/config.py 的 MOVE/DRIVE_*，
改配置不用动本文件。
"""
try:
    import asyncio
except ImportError:
    import uasyncio as asyncio

import time

from .. import config


# ==================================================================
# PCA9685 16 路 PWM 驱动（I2C），实现与 v3 实测可用的 motor_actor 逐字对齐。
# 引脚/通道见 docs/引脚分配与接线.md 与 config.MOVE。
# ==================================================================

class PCA9685:
    """PCA9685 PWM 驱动（MicroPython，纯 I2C，无第三方依赖）。"""

    REG_MODE1 = 0x00
    REG_PRESCALE = 0xFE
    REG_BASE = 0x06          # LED0_ON_L，每通道 4 字节 (ON_L,ON_H,OFF_L,OFF_H)
    OSC_CLOCK = 25000000     # 内部 25MHz

    def __init__(self, i2c, address=0x40):
        self.i2c = i2c
        self.address = address
        self.freq = 50
        self._w8(self.REG_MODE1, 0x00)     # 复位
        time.sleep_ms(5)

    # ---- 寄存器读写（writeto_mem/readfrom_mem）----
    def _w8(self, reg, val):
        self.i2c.writeto_mem(self.address, reg, bytes([val & 0xFF]))

    def _r8(self, reg):
        return self.i2c.readfrom_mem(self.address, reg, 1)[0]

    def _w4(self, reg, b0, b1, b2, b3):
        self.i2c.writeto_mem(self.address, reg, bytes([b0, b1, b2, b3]))

    # ---- 配置 ----
    def set_freq(self, freq_hz):
        """设置 PWM 频率（所有通道共享）。舵机标准 50Hz。"""
        prescale = int(25000000.0 / (4096 * freq_hz) + 0.5) - 1
        old = self._r8(self.REG_MODE1)
        self._w8(self.REG_MODE1, (old & 0x7F) | 0x10)   # sleep 才能写 PRESCALE
        self._w8(self.REG_PRESCALE, prescale)
        self._w8(self.REG_MODE1, old)                   # 唤醒
        time.sleep_ms(5)
        self._w8(self.REG_MODE1, old | 0xA1)            # restart + auto-increment
        self.freq = freq_hz

    def duty(self, channel, value):
        """占空比 0-4095（value<=0 全关，>=4095 全开）"""
        value = 0 if value < 0 else (4095 if value > 4095 else int(value))
        reg = self.REG_BASE + channel * 4
        if value == 0:
            self._w4(reg, 0, 0, 0x10, 0)                # OFF 置 0x1000：强制全关
        elif value >= 4095:
            self._w4(reg, 0, 0x10, 0, 0)                # ON 置 0x1000：强制全开
        else:
            self._w4(reg, 0, 0, value & 0xFF, (value >> 8) & 0xFF)

    def servo_angle(self, channel, angle):
        """舵机角度（0-180°）。50Hz(20ms) 下 0.5~2.5ms 脉宽 → duty ≈ 102~512"""
        angle = max(0.0, min(180.0, float(angle)))
        us = 500 + (2500 - 500) * angle / 180.0         # 0.5ms~2.5ms
        self.duty(channel, int(us / 20000.0 * 4096))


# ==================================================================
# 运动角色
# ==================================================================

class MoveWorker:
    """腿：pub/leg 收指令 → 串行执行（舵机就位/电机跑完时长才取下一条）。

    消费者型 worker（同 speak/camera）：阻塞在入站 get() 上，stop_token 哨兵
    即退出。PCA9685 未就绪时每次指令前都会重试初始化（接好线/供电后无需重启
    即可恢复），失败只报错不拖垮其它器官。
    """

    def __init__(self, queues, stop_token=None, pca9685=None):
        self.queues = queues
        self.stop_token = stop_token
        self.pwm = pca9685          # 可注入驱动（PC 冒烟/模拟用）；None=设备上自建

    # ====================================================== 硬件初始化
    async def _init_pwm(self):
        """初始化 PCA9685（I2C 扫描确认）。失败保持存活，下条指令再试。"""
        mv = config.MOVE
        try:
            from machine import I2C, Pin
            i2c = I2C(mv['i2c_id'], sda=Pin(mv['sda']), scl=Pin(mv['scl']),
                      freq=400000)
            found = i2c.scan()
            if mv['addr'] not in found:
                print('[move] PCA9685 未找到 (I2C 扫描: %r)，检查接线/供电'
                      % found)
                self.pwm = None
                return
            self.pwm = PCA9685(i2c, address=mv['addr'])
            self.pwm.set_freq(mv['freq'])
            # 上电默认：舵机归中、电机全停（防上电乱动）
            self.pwm.servo_angle(mv['ch_pan'], 90)
            self.pwm.servo_angle(mv['ch_tilt'], 90)
            self._stop_motors()
            print('[move] PCA9685 就绪（舵机归中 90/90，电机停止）')
        except Exception as e:
            print('[move] PCA9685 初始化失败，请检查接线: %s' % e)
            self.pwm = None

    # ====================================================== 电机控制
    def _stop_motors(self):
        if self.pwm is None:
            return
        mv = config.MOVE
        for ch in (mv['ch_left_a'], mv['ch_left_b'],
                   mv['ch_right_a'], mv['ch_right_b']):
            self.pwm.duty(ch, 0)

    def _motor(self, ch_a, ch_b, speed):
        """单个电机（DRV8833 双输入 H 桥）：
        speed>0 → A 端 PWM、B 端 0（正转）；speed<0 → 反转；0 → 停。"""
        if self.pwm is None:
            return
        speed = max(-100, min(100, int(speed)))
        if speed > 0:
            self.pwm.duty(ch_a, int(speed / 100.0 * 4095))
            self.pwm.duty(ch_b, 0)
        elif speed < 0:
            self.pwm.duty(ch_a, 0)
            self.pwm.duty(ch_b, int(-speed / 100.0 * 4095))
        else:
            self.pwm.duty(ch_a, 0)
            self.pwm.duty(ch_b, 0)

    def _drive_motors(self, left_speed, right_speed):
        """双电机驱动（含线序反转校准，与 v3 motor_actor 一致）"""
        mv = config.MOVE
        l = -left_speed if mv['invert_left'] else left_speed
        r = -right_speed if mv['invert_right'] else right_speed
        self._motor(mv['ch_left_a'], mv['ch_left_b'], l)
        self._motor(mv['ch_right_a'], mv['ch_right_b'], r)

    # ====================================================== 指令解析
    @staticmethod
    def _parse(msg):
        """解析消息为 (cmd, arg1, arg2)。
        支持 "[MOVE]:pan,90" / "pan 90" / "pan,90" / "forward,50,3"。
        arg2 = 可选第 3 参（电机持续秒数）。"""
        if isinstance(msg, bytes):
            text = msg.decode('utf-8', 'ignore')
        else:
            text = str(msg)
        text = text.strip()
        if text.startswith('[MOVE]:'):
            text = text[len('[MOVE]:'):].strip()
        parts = text.replace(' ', ',').split(',')
        parts = [p.strip() for p in parts if p.strip() != '']
        if not parts:
            return None, None, None
        cmd = parts[0].lower()
        arg1 = parts[1] if len(parts) > 1 else None
        arg2 = parts[2] if len(parts) > 2 else None
        return cmd, arg1, arg2

    @staticmethod
    def _seconds(arg, default):
        """解析持续秒数："3" / "1.5s" / "800ms" / "2秒"；未给/失败用 default；
        越界夹到 [DRIVE_SECONDS_MIN, DRIVE_SECONDS_MAX]。"""
        if arg is None:
            return default
        s = str(arg).strip().lower().replace('秒', '')
        try:
            if s.endswith('ms'):
                sec = float(s[:-2]) / 1000.0
            elif s.endswith('s'):
                sec = float(s[:-1])
            else:
                sec = float(s)
        except ValueError:
            print('[move] 持续时间无法解析 (%r)，用默认 %.1fs' % (arg, default))
            return default
        sec = max(config.DRIVE_SECONDS_MIN, min(config.DRIVE_SECONDS_MAX, sec))
        return sec

    # ====================================================== 指令执行
    async def _execute(self, cmd, arg1, arg2):
        """执行一条指令（串行：本协程跑完才轮到下一条）。"""
        mv = config.MOVE
        if self.pwm is None:
            print('[move] PCA9685 未就绪，忽略指令: %s' % cmd)
            return
        try:
            if cmd == 'pan':
                a = max(mv['pan_min'], min(mv['pan_max'], float(arg1)))
                self.pwm.servo_angle(mv['ch_pan'], a)
                print('[move] 云台水平 -> %d°（限幅 %d~%d）'
                      % (int(a), mv['pan_min'], mv['pan_max']))
            elif cmd == 'tilt':
                a = max(mv['tilt_min'], min(mv['tilt_max'], float(arg1)))
                self.pwm.servo_angle(mv['ch_tilt'], a)
                print('[move] 云台俯仰 -> %d°（限幅 %d~%d）'
                      % (int(a), mv['tilt_min'], mv['tilt_max']))
            elif cmd in ('forward', 'back', 'left', 'right'):
                s = int(float(arg1))          # 速度 0-100（_motor 内夹紧）
                if cmd == 'forward':
                    default = config.DRIVE_FORWARD_SECONDS
                    self._drive_motors(s, s)
                elif cmd == 'back':
                    default = config.DRIVE_FORWARD_SECONDS
                    self._drive_motors(-s, -s)
                elif cmd == 'left':
                    default = config.DRIVE_TURN_SECONDS
                    self._drive_motors(-s, s)   # 左轮反转、右轮正转
                else:
                    default = config.DRIVE_TURN_SECONDS
                    self._drive_motors(s, -s)   # 右轮反转、左轮正转
                sec = self._seconds(arg2, default)
                print('[move] %s %d%%（%.1fs 后自动停）'
                      % ({'forward': '前进', 'back': '后退', 'left': '原地左转',
                          'right': '原地右转'}[cmd], s, sec))
                try:
                    await asyncio.sleep(sec)     # 跑完时长（期间让出事件循环）
                finally:
                    self._stop_motors()          # 任何退出路径都保证电机停
                    print('[move] 电机已停')
            elif cmd in ('center', 'home', 'reset', 'zero'):
                self.pwm.servo_angle(mv['ch_pan'], 90)
                self.pwm.servo_angle(mv['ch_tilt'], 90)
                self._stop_motors()
                print('[move] 复位：云台回中(90/90)，电机停止')
            elif cmd == 'stop':
                self._stop_motors()
                print('[move] 电机停止')
            else:
                print('[move] 未知指令: %s' % cmd)
        except (TypeError, ValueError) as e:
            print('[move] 指令参数错误 (%s %s): %s' % (cmd, arg1, e))

    # ====================================================== 主循环
    async def run(self):
        """串行消费 pub/leg：一条做完（电机跑完时长）才取下一条。"""
        print('[move] 腿就绪：pub/leg 指令串行执行')
        if self.pwm is None:
            await self._init_pwm()
        while True:
            msg = await self.queues['pub/leg'].get()
            if self.stop_token is not None and msg is self.stop_token:
                break
            cmd, arg1, arg2 = self._parse(msg.payload)
            if cmd is None:
                continue
            if self.pwm is None:
                await self._init_pwm()     # 未就绪时每次指令前重试（自恢复）
            await self._execute(cmd, arg1, arg2)
