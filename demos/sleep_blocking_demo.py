# -*- coding: utf-8 -*-
"""
time.sleep 在多线程 vs 协程(asyncio)中的行为对比

"""

import asyncio
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor

# # Windows 下统一用 UTF-8 输出,避免中文在终端里乱码
# if sys.platform == "win32" and hasattr(sys.stdout, "reconfigure"):
#     sys.stdout.reconfigure(encoding="utf-8", errors="replace")


# ---------------------------------------------------------------
# Part 1:多线程 + time.sleep —— time.sleep 只阻塞【当前】线程
# ---------------------------------------------------------------
def worker_a():
    print("[Part1] A 开始:我准备睡 5 秒...")
    time.sleep(5)            # 只让【线程 A】睡觉
    print("[Part1] A 醒来:5 秒已过")


def worker_b():
    # B 完全没有 sleep,应该立刻执行,不用等 A
    print("[Part1] B 在跑:我不需要等 A!")
    time.sleep(3)
    print('[Part1] B 醒来:3 秒已过')


def part1_threads():
    print("=" * 62)
    print("Part 1:多线程 + time.sleep")
    print("现象:先看到 B 的输出,约 5 秒后才看到 A 醒来 -> 并行")
    print("=" * 62)

    t0 = time.perf_counter()
    ta = threading.Thread(target=worker_a)   # 创建线程 A
    tb = threading.Thread(target=worker_b)   # 创建线程 B
    ta.start()                               # 启动后由操作系统调度
    tb.start()
    ta.join()                                # 主线程等 A、B 结束
    tb.join()
    print(f"总耗时 {time.perf_counter() - t0:.1f} 秒(而不是 A 睡完再跑 B 的串行)")

def main():
    part1_threads()                    # ~5 秒
    print()

if __name__ == "__main__":
    main()
