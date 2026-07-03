"""Internal documentation."""
from __future__ import annotations

SERVER_NAME_PATTERN: str = r"^[A-Za-z0-9_-]+$"

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
