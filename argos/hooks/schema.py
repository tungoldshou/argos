"""Hooks JSON Schema 字面常量(spec §2.2)。

存 schema 字面常量供 config.load() 用 jsonschema 校验;不依赖 jsonschema 的运行时
不是 MVP 必备(本期不引入 jsonschema 依赖),改成手写最小校验:逐字段 type / required /
enum 检查。schema.py 只导常量(给未来要补 jsonschema strict mode 时用)。"""
from __future__ import annotations

# 已知事件名(spec §2.1);5/8 MVP 事件 + 留 v1.1 占位(校验时拒绝未知 event)
KNOWN_EVENTS: frozenset[str] = frozenset({
    "PreToolUse",
    "PostToolUse",
    "Stop",
    "UserPromptSubmit",
    "SessionStart",
    # v1.1 占位(本期拒):
    # "Notification", "PreCompact", "SessionEnd",
})

# HookHandler.type 允许值(MVP 仅 "command")
VALID_HANDLER_TYPES: frozenset[str] = frozenset({"command"})


# JSON Schema 字面(给未来 strict mode 用,本期不调)
SCHEMA_V1: dict = {
    "$schema": "http://json-schema.org/draft-07/schema#",
    "title": "Argos Hooks Config",
    "type": "object",
    "required": ["version", "hooks"],
    "properties": {
        "version": {"const": 1},
        "hooks": {
            "type": "object",
            "additionalProperties": {
                "type": "array",
                "items": {
                    "type": "object",
                    "required": ["hooks"],
                    "properties": {
                        "matcher": {"type": "string"},
                        "hooks": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "required": ["type", "command"],
                                "properties": {
                                    "type": {"enum": list(VALID_HANDLER_TYPES)},
                                    "command": {"type": "string", "minLength": 1},
                                    "timeout": {"type": "integer", "minimum": 1},
                                },
                                "additionalProperties": False,
                            },
                            "minItems": 1,
                        },
                    },
                },
            },
        },
    },
    "additionalProperties": False,
}
