
import xml.etree.ElementTree as ET

SHAPE = {
    'goal': {'id': None,
             'name': None,
             'content': None,
             'child-goals': {'goal-id': None},
             'father-goal-id': None,
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
}

def _names(shape) -> str:
    return '、'.join(f'<{tag}>' for tag in shape)

def _fit(node, shape, path) -> str:
    """node 底下符合 shape 吗：对不上返回原因，全对返回空串。
    """
    for child in node:
        if child.tag in shape:
            sub = shape[child.tag]
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
