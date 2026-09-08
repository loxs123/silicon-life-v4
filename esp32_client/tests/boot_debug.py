# 调试用最小 boot.py：不连 WiFi / 不校时 / 不启 WebREPL，
# 保证 reset 后立刻停在 REPL >>>，用于排查"开机卡死"是不是 boot.py 引起。
#
# 用法（覆盖设备根目录 boot.py）：
#     mpremote connect COM4 fs cp boot_debug.py :boot.py
#     mpremote connect COM4 reset
#     mpremote connect COM4 repl      # 应秒出 >>>
#
# 恢复真实 boot.py（仓库根目录这份就是你在用的版本）：
#     mpremote connect COM4 fs cp boot.py :boot.py
print('boot: DEBUG 模式（不连 WiFi / 不校时）')
