"""hook_examples —— hook 写法的小例子。

一个 hook = 一个文件 + 一个函数，函数名 = 文件名，第一个参数是 self。
hook 不会自动发现，按 HOOKS 的顺序注册：p.hooks = HOOKS
（Pipeline.process() 里是 hook(self)，self 就是那个 Pipeline）。

现在这里放的是三个测试 hook：leg_done 收腿的回执，probe_desktop 投一条截图指令，
probe_feishu 等一条飞书消息再发回去。
"""
from .probe_desktop import probe_desktop
from .probe_feishu import probe_feishu

HOOKS = [probe_desktop, probe_feishu]
