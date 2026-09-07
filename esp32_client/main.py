"""esp32 器官端入口 —— 对应 eq12_server/run.py。

上传到设备后由 main.py 启动（boot.py 已连好 WiFi）：
    MicroPython 设备文件布局：
        /boot.py        # 只联网（见本目录 boot.py）
        /main.py        # 本文件
        /src/...        # 本目录 src 整包上传

循环结构（asyncio）：
    MainLoop.run()
      ├─ AsyncMQTT.run()      引擎：连接/重连/订阅/读消息
      ├─ _publish_worker      sub/ear 专职发送任务
      ├─ EarWorker.run()      麦克风采集 → 上行
      └─ SpeakWorker.run()    下行 TTS → I2S 播放
"""
try:
    import asyncio
except ImportError:
    import uasyncio as asyncio

from src.main_loop import MainLoop


async def _main():
    await MainLoop().run()      # run() 阻塞到 stop() / Ctrl+C


if __name__ == '__main__':
    try:
        asyncio.run(_main())
    except KeyboardInterrupt:
        print('\n[main] Ctrl+C，退出')
