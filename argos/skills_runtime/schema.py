"""3 个内置 skill 的 parameters_schema 字面常量(spec §2.2)。

JSON Schema draft-07 字面;本期不调 jsonschema 库(避免依赖),手写最小校验
在 runner.py。schema 字段仅用于未来 LLM 提示 + /help 展示参数形状。"""
from __future__ import annotations

# /verify [path] —— path 可选,默认 workspace 根
VERIFY_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "path": {
            "type": "string",
            "description": "可选 path(workspace-relative);默认 = workspace 根",
        },
        "timeout": {
            "type": "integer",
            "minimum": 1,
            "maximum": 600,
            "default": 60,
            "description": "timeout 秒数(spec §2.3 / D11 默认 60)",
        },
    },
    "additionalProperties": False,
}

# /security-review [path] —— path 可选
SECURITY_REVIEW_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "path": {
            "type": "string",
            "description": "可选 path(workspace-relative);默认 = workspace 根",
        },
    },
    "additionalProperties": False,
}

# /simplify [path] [top] —— path / top 都可选
SIMPLIFY_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "path": {
            "type": "string",
            "description": "可选 path(workspace-relative);默认 = workspace 根",
        },
        "top": {
            "type": "integer",
            "minimum": 1,
            "maximum": 100,
            "default": 10,
            "description": "top-N 截断(spec D6 默认 10)",
        },
    },
    "additionalProperties": False,
}
