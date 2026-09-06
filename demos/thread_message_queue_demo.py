# -*- coding: utf-8 -*-
"""
线程共享消息队列的最小 demo(纯多线程,不涉及协程)

核心要点:
  1. 同一进程内,所有线程共享内存,天然可以"看到"同一个队列对象;
  2. queue.Queue 是线程安全的 FIFO 队列:内部用 锁 + 条件变量 实现,
     多个线程同时 put / get 不会数据错乱,也无需自己再加锁;
  3. q.get() 在队列为空时【阻塞等待】,有消息来了自动被唤醒;
  4. 约定用"毒丸"(None)作为停止信号,通知消费者收工;
  5. task_done() + join() 用于等待队列中所有消息被处理完。

运行方式:
    python demos/thread_message_queue_demo.py
"""

import queue
import random
import threading
import time
import sys

# Windows 下统一用 UTF-8 输出,避免中文乱码
if sys.platform == "win32" and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# 唯一的共享消息队列:所有线程都往这里放 / 从这里取
q = queue.Queue()


def producer(name: str, count: int):
    """生产者:往共享队列里放 count 条消息"""
    for i in range(1, count + 1):
        msg = f"{name} 的第 {i} 条消息"
        q.put(msg)                       # 线程安全,内部加锁,可直接调用
        print(f"[生产者 {name}] 放入 -> {msg}")
        time.sleep(random.uniform(0.05, 0.2))   # 模拟生产耗时


def consumer(name: str):
    """消费者:不停从共享队列取消息处理,收到 None 即收工"""
    while True:
        msg = q.get()                    # 队列为空时【阻塞】等待,不用轮询
        if msg is None:                  # 毒丸:停止信号
            q.task_done()
            print(f"[消费者 {name}] 收到停止信号,退出")
            break
        print(f"[消费者 {name}] 取出 <- {msg} (队列还剩 {q.qsize()} 条)")
        time.sleep(0.1)                  # 模拟处理耗时
        q.task_done()                    # 标记本条消息处理完毕


def main():
    num_consumers = 2
    num_producers = 2
    per_producer = 5

    # 先启动消费者(队列空时它们会阻塞在 q.get() 上等待)
    consumers = [
        threading.Thread(target=consumer, args=(f"C{i}",), daemon=True)
        for i in range(1, num_consumers + 1)
    ]
    for t in consumers:
        t.start()

    # 再启动生产者,两个生产者并发往【同一个队列】放消息
    producers = [
        threading.Thread(target=producer, args=(f"P{i}", per_producer))
        for i in range(1, num_producers + 1)
    ]
    for t in producers:
        t.start()

    # 等所有生产者放完
    for t in producers:
        t.join()
    print(f"\n所有生产者已放完,队列中还有 {q.qsize()} 条待处理\n")

    # 放 num_consumers 个毒丸,让每个消费者各收一个后退出
    for _ in range(num_consumers):
        q.put(None)

    # q.join():阻塞直到队列里所有消息(含毒丸)都调用了 task_done()
    q.join()
    print("\n所有消息处理完毕,队列已清空,程序结束")


if __name__ == "__main__":
    main()
