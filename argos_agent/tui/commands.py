"""slash 命令解析(spec §4.5)。纯解析,不渲染、不副作用——app.py 拿 SlashCommand 后分发。

MVP 子集:/yolo /undo /clear /retry /status /model /resume /cost
能力可见:/help /tools /skills /mcp
"""
from __future__ import annotations

from dataclasses import dataclass

COMMAND_NAMES: list[str] = [
    "yolo", "undo", "clear", "retry", "status", "model", "resume", "cost",
    "help", "tools", "skills", "mcp",
]


@dataclass(frozen=True, slots=True)
class SlashCommand:
    name: str
    arg: str
    known: bool


def parse_slash(text: str) -> SlashCommand | None:
    """文本以 / 开头才视为命令;返回 (name, arg, known)。非命令返回 None。"""
    s = text.strip()
    if not s.startswith("/"):
        return None
    body = s[1:].strip()
    if not body:
        return None
    parts = body.split(None, 1)
    name = parts[0].lower()
    arg = parts[1].strip() if len(parts) > 1 else ""
    return SlashCommand(name=name, arg=arg, known=name in COMMAND_NAMES)
