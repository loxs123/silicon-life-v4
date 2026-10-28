
import xml.etree.ElementTree as ET

# 每种节点该长的样子：{子标签: 它自己的样子}，None 表示叶子、不再往下查。
# 和 ../protocols/*.xml 对得上；同一个标签出现多次时，每一份都要符合。
ATOM = {'queue': None,        # 载荷字段随队列不同，先按并集放行
        'text': None,
        'type': None,
        'value': None,
        'direction': None,
        'time': None,
        'img': None,
        'in': None}

SUB_GOAL = {'name': None,
            'content': None}

SHAPE = {
    'goal': {'id': None,
             'name': None,
             'content': None,
             'create-time': None,
             'finish-time': None},
    'skill': {'id': None,
              'type': None,
              'name': None,
              'tags': {'tag': None},
              'description': None,
              'target': None,
              'steps': {'step': {'step-name': None, 'step-content': None}},
              'notes': {'note': None},
              'verify': None,
              'output': None},
    'memory': {'id': None,
               'name': None,
               'tags': {'tag': None},
               'description': None,
               'content': None,
               'time': None,
               'related-skills': {'skill': {'id': None, 'reason': None}},
               'related-memorys': {'memory': {'id': None, 'reason': None}}},
    'atom_action': ATOM,
    'atom_actions': {'atom_action': ATOM},
    'sub_goal': SUB_GOAL,
    'sub_goals': {'sub_goal': SUB_GOAL},
}

TREE = ('goal',)      # 只有这些节点里能挂别的已知节点（目标树），其它容器一律按 shape 来

def _names(shape) -> str:
    return '、'.join(f'<{tag}>' for tag in shape)

def _fit(node, shape, path) -> str:
    """node 底下符合 shape 吗：对不上返回原因，全对返回空串。
    """
    for child in node:
        if child.tag in shape:
            sub = shape[child.tag]
        elif path.split('/')[0] in TREE and child.tag in SHAPE:   # goal 里可以挂 skill / sub_goal …
            sub = SHAPE[child.tag]
        elif shape:
            return f'{path} 里不认识 <{child.tag}>，只能有 {_names(shape)}'
        else:
            return f'{path} 里不认识 <{child.tag}>'
        reason = _fit(child, sub or {}, f'{path}/{child.tag}')
        if reason:
            return reason
    return ''

def check(text: str, tag: str = '', shape=None) -> str:
    """检查字符串能不能当一个 XML 节点用（loader.append_node / edit_node 的入参）。
    """
    try:
        node = ET.fromstring(text)
    except ET.ParseError as err:
        return f'不是合法 XML：{err}'
    if tag and node.tag != tag:
        return f'根标签是 <{node.tag}>，要的是 <{tag}>'
    if shape is None:
        if node.tag not in SHAPE:
            return f'不认识的根标签 <{node.tag}>，只能是 {_names(SHAPE)}'
        shape = SHAPE[node.tag]
    return _fit(node, shape, node.tag)
