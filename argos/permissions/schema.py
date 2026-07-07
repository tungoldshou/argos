from __future__ import annotations

from typing import Final

VALID_MODES: Final[frozenset[str]] = frozenset({"smart", "full"})

SCHEMA_V2: Final[dict] = {
    "type": "object",
    "required": ["version"],
    "properties": {
        "version": {"const": 2},
        "mode": {"type": "string", "enum": sorted(VALID_MODES)},
        "network": {"type": "object"},
        "reviewer": {"type": "object"},
        "rules": {
            "type": "object",
            "properties": {
                "allow": {"$ref": "#/$defs/rule_list"},
                "deny": {"$ref": "#/$defs/rule_list"},
                "ask": {"$ref": "#/$defs/rule_list"},
            },
            "additionalProperties": False,
        },
    },
    "$defs": {
        "rule_list": {
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
    },
    "additionalProperties": False,
}
