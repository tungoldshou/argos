from __future__ import annotations

KNOWN_EVENTS: frozenset[str] = frozenset({
    "PreToolUse",
    "PostToolUse",
    "Stop",
    "UserPromptSubmit",
    "SessionStart",
    # "Notification", "PreCompact", "SessionEnd",
})

VALID_HANDLER_TYPES: frozenset[str] = frozenset({"command"})


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
