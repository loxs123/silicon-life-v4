from queue import Queue


class EarWorker:
    """每器官一个 worker：消费 sub/ear 入站队列做 ASR 等。

    stop_token 是主循环停机时投进 sub/* 队列的 _STOP 哨兵对象，
    run() get() 到它即退出（不把它当业务数据处理），用于优雅停机。
    """

    def __init__(self, queues: dict[str, Queue], stop_token=None):
        self.queues = queues
        self.stop_token = stop_token

    def run(self):
        while True:
            item = self.queues['sub/ear'].get()
            if self.stop_token is not None and item is self.stop_token:
                break
            sound = item
            # TODO: ASR
            # text = self.asr(sound)
            # 发送方向按协议约定：若大脑订阅 pub/brain 则写 self.queues['pub/brain']
            ...
