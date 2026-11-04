"""[goal] 收消息 → 选当前 goal → GOAL CHECKER。

- 收：外来消息各建一个根 goal；动作回执记进日志。只 get_nowait，不等。
- 选：外来消息的根先办，再办今天的计划（goal 1），走到第一个没完成的叶子。
      子 goal 全部完成的父 goal 直接完成。
- 判：做过动作、还没判过 → 问模型「完成了吗」，只答 是 / 否。
"""
import base64
import json
import os
import queue
import time
import xml.etree.ElementTree as ET

from ..info import Info

# goal-adjustor 放在这里完成
# 上一个目标失败也需要调整目标树
def hook(cur_info: Info):
    ...
