"""按 protocols-json/*.json 校验模型给的 dict。"""

import jsonschema

SCHEMA = {
    'goal': {
        "type": "object",
        "properties": {
            "id":              {"type": "integer"},
            "name":            {"type": "string"},
            "content":         {"type": "string"},
            "child-goals":     {"type": "array"},
            "father-goal-id":  {"type": "integer"},
            "create-time":     {"type": "string"},
            "finish-time":     {"type": "string"},
        },
        "required": ["id", "name", "content", "child-goals",
                    "father-goal-id", "create-time", "finish-time"],
        "additionalProperties": False,
    },
    'skill': {
        "type": "object",
        "properties": {
            "id":          {"type": "integer", "minimum": 0},
            "type":        {"type": "string", "enum": ["子目标", "原子动作"]},
            "name":        {"type": "string", "minLength": 1},
            "tags": {
                "type": "array",
                "items": {"type": "string", "minLength": 1},
                "minItems": 1,              # 至少一个
                "uniqueItems": True,
            },
            "description": {"type": "string", "minLength": 1},
            "target":      {"type": "string", "minLength": 1},
            "steps": {
                "type": "array",
                "minItems": 1,
                "items": {
                    "type": "object",
                    "properties": {
                        "step-name":    {"type": "string", "minLength": 1},
                        "step-content": {"type": "string", "minLength": 1},
                    },
                    "required": ["step-name", "step-content"],
                    "additionalProperties": False,
                },
            },
            "notes": {
                "type": "array",
                "items": {"type": "string", "minLength": 1},
                "minItems": 1,              # 至少一条
            },
            "verify": {"type": "string", "minLength": 1},
            "output": {"type": "string", "minLength": 1},
        },
        "required": ["id", "type", "name", "tags", "description",
                    "target", "steps", "notes", "verify", "output"],
        "additionalProperties": False,
    },
    'memory':  {
        "type": "object",
        "properties": {
            "id": {
                "type": "integer",   # 新建时可为 null
                "minimum": 0,
            },
            "name":        {"type": "string", "minLength": 1},
            "tags": {
                "type": "array",
                "items": {"type": "string", "minLength": 1},
                "minItems": 1,                 # 至少一个
                "uniqueItems": True,
            },
            "description": {"type": "string", "minLength": 1},
            "content":     {"type": "string", "minLength": 1},
            "time": {
                "type": "string",
                # "2026-11-06 14:20:00" 格式
                "pattern": r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$",
            },
            "related-skills": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "id":     {"type": "integer", "minimum": 0},
                        "reason": {"type": "string", "minLength": 1},
                    },
                    "required": ["id", "reason"],
                    "additionalProperties": False,
                },
            },
            "related-memorys": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "id":     {"type": "integer", "minimum": 0},
                        "reason": {"type": "string", "minLength": 1},
                    },
                    "required": ["id", "reason"],
                    "additionalProperties": False,
                },
            },
        },
        "required": ["id", "name", "tags", "description", "content", "time",
                    "related-skills", "related-memorys"],
        "additionalProperties": False,
    },
}

def check(data, kind):
    try:
        jsonschema.validate(instance=data, schema=SCHEMA[kind])
        return True, None
    except jsonschema.ValidationError as e:
        return False, str(e)


if __name__ == '__main__':
    data = {
        "id": 1,
        "name": "用户偏好",
        "tags": ["偏好"],
        "description": "记录用户喜欢深色主题",
        "content": "用户明确表示偏好深色模式，后续 UI 默认深色",
        "time": "2026-11-06 14:20:00",
        "related-skills": [{"id": 7, "reason": "这次就是用它做的"}],
        "related-memorys": [],
    }
    print(check(data, 'memory'))
