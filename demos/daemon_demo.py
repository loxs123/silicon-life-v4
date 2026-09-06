# -*- coding: utf-8 -*-
"""
daemon=True(守护线程)是什么意思?

核心规则:
  1. 默认 daemon=False(非守护):
     主线程代码跑完后,进程会【继续等待】所有非守护线程结束才退出;
  2. daemon=True(守护):
     主线程代码一跑完,进程【立即退出】,
     守护线程被强制掐断 —— 哪怕它活还没干完、代码才执行到一半。

运行方式:
    python demos/daemon_demo.py
"""

import threading
import time
import sys

if sys.platform == "win32" and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def worker(name: str, seconds: float):
    print(f"[{name}] 开工,准备干 {seconds} 秒", flush=True)
    time.sleep(seconds)
    print(f"[{name}] 干完了(这行能否打印是关键证据)", flush=True)


def part1_daemon():
    """守护线程:主线程一结束,进程直接退出,线程被掐死"""
    print("=" * 60)
    print("Part 1: daemon=True(守护线程)")
    print("=" * 60)
    t = threading.Thread(target=worker, args=("守护线程", 3), daemon=True)
    t.start()

    time.sleep(1)          # 主线程干 1 秒的活
    print("[主线程] 干完 1 秒的活,主线程代码结束", flush=True)
    # 主线程结束 -> 进程立即退出,守护线程还剩 2 秒没干完,被掐死
    # (所以下面 main() 里 '程序正常结束' 会在此时打印,而守护线程的收尾不打印)


def part2_non_daemon():
    """非守护线程:主线程结束后进程仍被拖住,等它跑完才退出"""
    print()
    print("=" * 60)
    print("Part 2: daemon=False(默认,非守护线程)")
    print("=" * 60)
    t = threading.Thread(target=worker, args=("非守护线程", 3), daemon=False)
    t.start()

    time.sleep(1)          # 主线程干 1 秒的活
    print("[主线程] 干完 1 秒的活,主线程代码结束", flush=True)
    # 主线程代码虽结束,但进程会继续等非守护线程跑完剩下的 2 秒


def main():
    part1_daemon()
    print("[主线程] 程序即将退出", flush=True)
    # Part1 里守护线程被掐死 -> 进程立刻结束,不会等它

    # ---- 到这里进程已经退了,Part 2 实际上不会执行 ----
    # 想看 Part 2 的话:注释掉上面 part1_daemon() 再运行
    # part2_non_daemon()
    # print("[主线程] 程序即将退出", flush=True)


if __name__ == "__main__":
    main()
