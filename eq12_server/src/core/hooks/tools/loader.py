
from datetime import date, datetime
import os
import xml.etree.ElementTree as ET

class BaseLoader:
    def __init__(self, _id):
        self._id = _id
        self._load()
    
    def _base_path(self, ):
        raise NotImplementedError
    
    def _load(self, id):
        path = self._base_path()
        tree = ET.parse(goal_path)
        root = tree.getroot()
        for i, elem in enumerate(root.iter(), start=1):
            elem.set('id', str(i))
        
        self.tree = tree
        self.root = root
        self.cur_id = i + 1

    def _find(self, id):
        """返回 (parent, elem)；根元素 parent 为 None；找不到返回 (None, None)"""
        target = str(id)
        for parent in self.root.iter():
            for child in parent:
                if child.get('id') == target:
                    return parent, child
        if self.root.get('id') == target:
            return None, self.root
        return None, None

    def append_node(self, id, node_content: str):
        # id 是最低级非叶子节点，直接在它下面 append
        _, elem = self._find(id)
        if elem is None:
            raise KeyError(f'找不到 id={id}')
        new_elem = ET.fromstring(node_content)
        new_elem.set('id', str(self.cur_id))
        elem.append(new_elem)
        self.cur_id += 1

    def edit_node(self, id, node_content: str):
        # 只替换叶子：找父元素，原位替换，保持 id
        parent, elem = self._find(id)
        if elem is None:
            raise KeyError(f'找不到 id={id}')
        if parent is None:
            # 根元素是叶子（无子节点）才会走到这，直接换根
            new_elem = ET.fromstring(node_content)
            new_elem.set('id', str(id))
            self.root = new_elem
            self.tree._setroot(new_elem)
            return
        new_elem = ET.fromstring(node_content)
        new_elem.set('id', str(id))
        pos = list(parent).index(elem)
        parent.remove(elem)
        parent.insert(pos, new_elem)      # 保持原位置

    def del_node(self, id):
        # 只删叶子：找父元素 remove 即可
        parent, elem = self._find(id)
        if elem is None:
            raise KeyError(f'找不到 id={id}')
        if parent is None:
            raise ValueError('不能删除根元素')
        parent.remove(elem)
    @property
    def text(self):
        return ET.tostring(self.root, encoding='unicode')

    @property
    def id(self):
        return self.root.findtext('id')

    @property
    def name(self):
        return self.root.findtext('name')

class GoalLoader(BaseLoader):
    def _base_path(self):
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        goal_path = os.path.join(root, 'states', str(date.today()), f'goal_{self._id:04d}.xml')
        return goal_path
    
    @property
    def content(self):
        return self.root.findtext('content')

    @property
    def create_time(self):
        return self.root.findtext('create-time')

    @property
    def finish_time(self):
        return self.root.findtext('finish-time')

class SkillLoader(BaseLoader):
    def _base_path(self):
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        goal_path = os.path.join(root, 'skills', str(date.today()), f'skill_{self._id:04d}.xml')
        return goal_path

    @property
    def tags(self):
        """返回tags列表"""
        return [t.text for t in root.findall('tags/tag')]
    
    @property
    def description(self):
        return self.root.findtext('description')


class MemoryLoader(BaseLoader):
    def _base_path(self):
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        goal_path = os.path.join(root, 'memory', str(date.today()), f'memory_{self._id:04d}.xml')
        return goal_path
    
    @property
    def tags(self):
        """返回tags列表"""
        return [t.text for t in root.findall('tags/tag')]
    
    @property
    def description(self):
        return self.root.findtext('description')

if __name__ == '__main__':
    goal_loader = GoalLoader(1)
    print(goal_loader.text)
    goal_loader.append_node(1, '<skill>123</skill>')
    goal_loader.append_node(1, '<skill>123</skill>')
    print(goal_loader.cur_id)
    print(goal_loader.text)

