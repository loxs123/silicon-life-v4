import os
import shutil
from datetime import date, datetime, timedelta

from ...config import DREAM_NIGHT_START

HOOKS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'hooks')


def _dream_day():
    today = date.today()
    return today + timedelta(days=1) if datetime.now().hour >= DREAM_NIGHT_START else today


def _copy_day(kind, day):
    root = os.path.join(HOOKS_DIR, kind)
    target = os.path.join(root, str(day))
    if os.path.isdir(target):
        return
    name = str(day)
    days = []
    if os.path.isdir(root):
        days = sorted(d for d in os.listdir(root)
                      if len(d) == 10 and d[4] == '-' and d[7] == '-' and d.replace('-', '').isdigit()
                      and d < name)
    prev = os.path.join(root, days[-1] if days else 'seed')
    if os.path.isdir(prev):
        shutil.copytree(prev, target, ignore=shutil.ignore_patterns('.gitkeep'))
    else:
        os.makedirs(target, exist_ok=True)


def hook(self):
    day = _dream_day()
    _copy_day('skills', day)
    _copy_day('memory', day)
