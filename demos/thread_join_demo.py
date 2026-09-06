# -*- coding: utf-8 -*-
"""
验证: t1.join() 会不会阻塞 t2.join()?

结论:
  1. join() 阻塞的是【调用它的线程】(通常是主线程),不是目标线程;
  2. 两个线程都先 start() 再依次 join():
     主线程等 t1 期间,t2 一直在并行跑;
     若 t2 已提前跑完,t2.join() 会瞬间返回;
  3. 所以两个 join 的总耗时约等于 max(t1, t2),而不是 t1 + t2。

运行方式:
    python demos/thread_join_demo.py
"""

import threading
import time
import sys

if sys.platform == "win32" and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

t0 = time.perf_counter()


def worker(name: str, seconds: float):
    time.sleep(seconds)
    print(f"[{name}] 干完活了,此刻 {time.perf_counter() - t0:.2f}s", flush=True)


def main():
    # 两个线程先都启动,并行开跑
    t1 = threading.Thread(target=worker, args=("t1(睡3秒)", 3))
    t2 = threading.Thread(target=worker, args=("t2(睡1秒)", 1))
    t1.start()
    t2.start()

    # 主线程先等 t1
    t1.join()
    print(f"[主线程] t1.join() 返回了,此刻 {time.perf_counter() - t0:.2f}s")

    # 再等 t2
    t2.join()
    print(f"[主线程] t2.join() 返回了,此刻 {time.perf_counter() - t0:.2f}s")

    print(f"\n总耗时 {time.perf_counter() - t0:.2f}s")
    print("观察点:等 t1 的 3 秒里 t2 早就跑完了,")
    print("所以 t2.join() 几乎瞬间返回,总耗时约 3s 而不是 3+1=4s")


if __name__ == "__main__":
    main()
