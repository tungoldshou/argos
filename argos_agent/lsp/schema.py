"""LSP JSON Schema 字面常量(spec §2.2)。

存 schema 字面常量供 config.load() 校验;本期不调 jsonschema 库(避免引入依赖),
手写最小校验:逐字段 type / required / enum 检查。schema.py 只导常量。"""
from __future__ import annotations

# 合法 server name 正则(spec §2.2)
SERVER_NAME_PATTERN: str = r"^[A-Za-z0-9_-]+$"

# JSON Schema 字面(给未来 strict mode 用,本期不调)
SCHEMA_V1: dict = {
    "$schema": "http://json-schema.org/draft-07/schema#",
    "title": "Argos LSP Config",
    "type": "object",
    "required": ["version", "servers"],
    "properties": {
        "version": {"const": 1},
        "servers": {
            "type": "object",
            "additionalProperties": {
                "type": "object",
                "required": ["command", "filetypes"],
                "properties": {
                    "command": {
                        "type": "array",
                        "items": {"type": "string", "minLength": 1},
                        "minItems": 1,
                    },
                    "filetypes": {
                        "type": "array",
                        "items": {"type": "string", "pattern": r"^\.[A-Za-z0-9]+$"},
                        "minItems": 1,
                    },
                    "init_options": {"type": "object"},
                    "disabled": {"type": "boolean"},
                    "env": {
                        "type": "object",
                        "additionalProperties": {"type": "string"},
                    },
                },
                "additionalProperties": False,
            },
        },
    },
    "additionalProperties": False,
}
