"""permissions.json JSON Schema 字面常量 + 合法 ApprovalLevel 集合(spec §2.5)。"""
from __future__ import annotations

from typing import Final

# 合法 ApprovalLevel 字符串(对应 argos.approval.ApprovalLevel value)
VALID_LEVELS: Final[frozenset[str]] = frozenset({
    "observe", "propose", "confirm", "auto", "accept_edits",
})

# JSON Schema 字面常量(draft-07,纯数据;本期不调 jsonschema 库)
SCHEMA_V1: Final[dict] = {
    "type": "object",
    "required": ["version"],
    "properties": {
        "version": {"const": 1},
        "default_level": {"type": "string", "enum": list(VALID_LEVELS)},
        "tools": {
            "type": "object",
            "additionalProperties": {"type": "string", "enum": list(VALID_LEVELS)},
        },
        "allow": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["tool", "matcher"],
                "properties": {
                    "tool": {"type": "string", "minLength": 1},
                    "matcher": {"type": "string", "minLength": 0, "maxLength": 256},
                },
            },
        },
        "deny": {"$ref": "#/properties/allow"},
        "ask": {"$ref": "#/properties/allow"},
    },
    "additionalProperties": False,
}
