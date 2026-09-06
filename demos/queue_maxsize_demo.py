# -*- coding: utf-8 -*-
"""
验证 queue.Queue 的 maxsize 语义

结论:
  1. Queue() / Queue(maxsize=0)  -> 无上限队列:put 永远不会因"满了"而阻塞;
  2. Queue(maxsize=N)            -> 有限队列:放满 N 条后,
        put() 默认【阻塞】等待(直到有人 get 腾出位置);
        put_nowait() 则立刻抛 queue.Full;
  3. 所谓"无限"只是队列自身不设限,实际仍受内存限制:
     生产者比消费者快且永不停止时,队列会无限增长直到内存耗尽。

运行方式:
    python demos/queue_maxsize_demo.py
"""

import queue
import sys

if sys.platform == "win32" and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def part1_unbounded():
    """不传 maxsize -> 无限队列,放多少都立刻成功"""
    print("=" * 60)
    print("Part 1:Queue() 不传 maxsize(默认 0 = 无限)")
    print("=" * 60)
    q = queue.Queue()            # 等价于 queue.Queue(maxsize=0)
    for i in range(1000):        # 一口气放 1000 条,一次都不会阻塞
        q.put(f"消息{i}")
    print(f"放入 1000 条成功,当前队列长度: {q.qsize()} -> 队列自己完全不设限")


def part2_bounded():
    """maxsize=2 -> 有限队列,放满后 put_nowait 立刻抛 Full"""
    print()
    print("=" * 60)
    print("Part 2:Queue(maxsize=2) -> 有限队列")
    print("=" * 60)
    q = queue.Queue(maxsize=2)
    q.put_nowait("第1条")        # 放得下
    q.put_nowait("第2条")        # 放得下
    print("已放入 2 条(队列已满)")

    try:
        q.put_nowait("第3条")    # 满了 -> 不等待,直接抛异常
        print("第3条放入成功(不会走到这里)")
    except queue.Full:
        print("put_nowait 第3条 -> 抛出 queue.Full(队列已满)")

    print("而 put()(不带 nowait)则会一直阻塞等待,直到有人取走一条为止")


def main():
    part1_unbounded()
    part2_bounded()


if __name__ == "__main__":
    main()
