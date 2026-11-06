"""goal / skill / memory 的 XML 文件读写（格式见 hooks/protocols/）。

一个 loader 对应一个文件：states|skills|memory/<今天>/<前缀>_NNNN.xml，
seed 带过来的具名文件（如 skill_creator.xml）用名字打开。
载入时给每个元素编号（id 属性），append_node / edit_node / del_node 按编号改，save() 落盘。
"""
from datetime import date
import os
import re
import shutil
import time
import xml.etree.ElementTree as ET

HOOKS_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_DAY_RE = re.compile(r'^\d{4}-\d{2}-\d{2}$')


def day_dir(kind):
    """当天目录；不存在就从最近一天（没有就 seed）复制。states 不复制：目标每天重新定。"""
    root = os.path.join(HOOKS_DIR, kind)
    d = os.path.join(root, str(date.today()))
    if not os.path.isdir(d):
        days = sorted(x for x in os.listdir(root) if _DAY_RE.match(x)) if os.path.isdir(root) else []
        prev = os.path.join(root, days[-1] if days else 'seed')
        if kind != 'states' and os.path.isdir(prev):
            shutil.copytree(prev, d, ignore=shutil.ignore_patterns('.gitkeep'))
        else:
            os.makedirs(d, exist_ok=True)
    return d


class BaseLoader:
    KIND = ''      # 目录：states / skills / memory
    PREFIX = ''    # 文件前缀：goal / skill / memory

    def __init__(self, _id):
        self._id = _id
        self._load()

    # ---------- 文件 ----------

    @classmethod
    def _file(cls, _id):
        name = '%s_%04d' % (cls.PREFIX, _id) if isinstance(_id, int) else _id
        return os.path.join(day_dir(cls.KIND), name + '.xml')

    def _base_path(self):
        return self._file(self._id)

    def _load(self):
        self.tree = ET.parse(self._base_path())
        self.root = self.tree.getroot()
        for i, elem in enumerate(self.root.iter(), start=1):
            elem.set('id', str(i))
        self.cur_id = i + 1

    def save(self):
        with open(self._base_path(), 'w', encoding='utf-8') as f:
            f.write(self.raw)

    @classmethod
    def new(cls, node_content: str):
        """新建文件：编号 = 当天最大编号 + 1，写进 <id>。"""
        _id = max(cls.ids(), default=0) + 1
        root = ET.fromstring(node_content)
        if root.find('id') is None:
            ET.SubElement(root, 'id')
        root.find('id').text = str(_id)
        with open(cls._file(_id), 'w', encoding='utf-8') as f:
            f.write(ET.tostring(root, encoding='unicode'))
        return cls(_id)

    @classmethod
    def ids(cls):
        pat = re.compile(r'^%s_(\d{4})\.xml$' % cls.PREFIX)
        return sorted(int(m.group(1)) for m in map(pat.match, os.listdir(day_dir(cls.KIND))) if m)

    @classmethod
    def all(cls):
        """当天目录里所有文件，含 seed 带过来的具名文件。"""
        pat = re.compile(r'^%s_(\d{4})$' % cls.PREFIX)
        names = sorted(f[:-4] for f in os.listdir(day_dir(cls.KIND)) if f.endswith('.xml'))
        return [cls(int(pat.match(n).group(1)) if pat.match(n) else n) for n in names]

    # ---------- 按元素编号改 ----------

    def _find(self, id):
        """返回 (parent, elem)；根元素 parent 为 None；找不到返回 (None, None)"""
        target = str(id)
        if self.root.get('id') == target:
            return None, self.root
        for parent in self.root.iter():
            for child in parent:
                if child.get('id') == target:
                    return parent, child
        return None, None

    def elem_id(self, tag):
        elem = self.root.find(tag)
        return elem.get('id') if elem is not None else None

    def append_node(self, id, node_content: str):
        """在元素 id 下面追加一个子元素。"""
        _, elem = self._find(id)
        if elem is None:
            raise KeyError(f'找不到 id={id}')
        new_elem = ET.fromstring(node_content)
        new_elem.set('id', str(self.cur_id))
        elem.append(new_elem)
        self.cur_id += 1

    def edit_node(self, id, node_content: str):
        """原位替换元素 id，编号不变。"""
        parent, elem = self._find(id)
        if elem is None:
            raise KeyError(f'找不到 id={id}')
        new_elem = ET.fromstring(node_content)
        new_elem.set('id', str(id))
        if parent is None:
            self.root = new_elem
            self.tree._setroot(new_elem)
            return
        pos = list(parent).index(elem)
        parent.remove(elem)
        parent.insert(pos, new_elem)

    def del_node(self, id):
        parent, elem = self._find(id)
        if elem is None:
            raise KeyError(f'找不到 id={id}')
        if parent is None:
            raise ValueError('不能删除根元素')
        parent.remove(elem)

    # ---------- 字段 ----------

    @property
    def text(self):
        """带元素编号，给 append_node / edit_node 定位用。"""
        return ET.tostring(self.root, encoding='unicode')

    @property
    def raw(self):
        """不带元素编号，落盘和给模型看都用它。"""
        clean = ET.fromstring(self.text)
        for elem in clean.iter():
            elem.attrib.pop('id', None)
        return ET.tostring(clean, encoding='unicode')

    @property
    def id(self):
        return self.root.findtext('id')

    @property
    def name(self):
        return self.root.findtext('name')


class GoalLoader(BaseLoader):
    KIND, PREFIX = 'states', 'goal'

    @property
    def content(self):
        return self.root.findtext('content')

    @property
    def create_time(self):
        return self.root.findtext('create-time')

    @property
    def finish_time(self):
        return (self.root.findtext('finish-time') or '').strip()

    @property
    def father(self):
        v = (self.root.findtext('father-goal-id') or '').strip()
        return int(v) if v else None

    @property
    def children(self):
        return [int(g.text) for g in self.root.findall('child-goals/goal-id') if (g.text or '').strip()]

    def add_child(self, child_id):
        self.append_node(self.elem_id('child-goals'), f'<goal-id>{child_id}</goal-id>')
        self.save()

    def finish(self):
        self.edit_node(self.elem_id('finish-time'),
                       '<finish-time>%s</finish-time>' % time.strftime('%Y-%m-%d %H:%M:%S'))
        self.save()


class SkillLoader(BaseLoader):
    KIND, PREFIX = 'skills', 'skill'

    @property
    def type(self):
        return (self.root.findtext('type') or '').strip()

    @property
    def tags(self):
        return [t.text for t in self.root.findall('tags/tag')]

    @property
    def description(self):
        return self.root.findtext('description')

    @property
    def target(self):
        return self.root.findtext('target')

    @property
    def verify(self):
        return self.root.findtext('verify')


class MemoryLoader(BaseLoader):
    KIND, PREFIX = 'memory', 'memory'

    @property
    def tags(self):
        return [t.text for t in self.root.findall('tags/tag')]

    @property
    def description(self):
        return self.root.findtext('description')

    @property
    def content(self):
        return self.root.findtext('content')


if __name__ == '__main__':
    g = GoalLoader.new('<goal><id/><name>试一下</name><content>测试</content><child-goals/>'
                       '<father-goal-id/><create-time>%s</create-time><finish-time/></goal>'
                       % time.strftime('%Y-%m-%d %H:%M:%S'))
    g.add_child(2)
    g.finish()
    print(GoalLoader(int(g.id)).text)
