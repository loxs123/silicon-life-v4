"""[测试] 截一次屏，再把鼠标顶到右上角。"""
import queue

from ...workers.desktop_worker import PUB_QUEUE, SUB_QUEUE

COMMANDS = (
    {'type': 'screenshot'},
    {'type': 'mouse', 'direction': 'UP', 'value': 10000},
    {'type': 'mouse', 'direction': 'RIGHT', 'value': 10000},
)


def probe_desktop(self):
    if self.user_info.get('probe_desktop_done'):
        return
    self.user_info['probe_desktop_done'] = True

    for cmd in COMMANDS:
        self.queues[PUB_QUEUE].put(cmd)
        print('[brain] probe_desktop → %s: %s' % (PUB_QUEUE, cmd), flush=True)

    for _ in range(4):
        try:
            item = self.queues[SUB_QUEUE].get(timeout=3)
        except queue.Empty:
            break
        if item.get('type') == 'screen':
            print('[brain] probe_desktop ← %s: 截图 %sx%s %s 字节'
                  % (SUB_QUEUE, item['width'], item['height'], item['size']),
                  flush=True)
        else:
            print('[brain] probe_desktop ← %s: %s' % (SUB_QUEUE, item), flush=True)
