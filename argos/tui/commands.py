"""Internal documentation."""
from __future__ import annotations

from dataclasses import dataclass

from argos.i18n import t

_COMMAND_KEYS: list[str] = [
    "help", "setup", "voice", "tools", "skills", "mcp", "model", "status", "cost",
    "resume", "clear", "yolo", "trust", "undo", "ledger", "journal", "retry",
    "plan", "hooks", "lsp", "permissions", "runs", "orders", "confirm", "dismiss",
    "dream", "verify", "security-review", "simplify", "eval", "routing", "context",
    "loop", "goal", "schedule", "watch",
]


def _build_command_help() -> dict[str, str]:
    """Internal documentation."""
    return {name: t(f"cmd.{name}") for name in _COMMAND_KEYS}


COMMAND_HELP: dict[str, str] = _build_command_help()

COMMAND_NAMES: list[str] = list(COMMAND_HELP)

_HIDDEN_KNOWN: frozenset[str] = frozenset({"remember", "forget", "memory"})


def match_commands(text: str) -> list[tuple[str, str]]:
    """Internal documentation."""
    s = text.lstrip()
    if not s.startswith("/"):
        return []
    body = s[1:]
    if " " in body:
        return []
    pref = body.lower()
    command_help = _build_command_help()
    prefix_matches = [(n, d) for n, d in command_help.items() if n.startswith(pref)]
    if prefix_matches or not pref:
        return prefix_matches
    return [(n, d) for n, d in command_help.items() if pref in n]


@dataclass(frozen=True, slots=True)
class SlashCommand:
    name: str
    arg: str
    known: bool


def parse_slash(text: str) -> SlashCommand | None:
    """Internal documentation."""
    s = text.strip()
    if not s.startswith("/"):
        return None
    body = s[1:].strip()
    if not body:
        return None
    parts = body.split(None, 1)
    name = parts[0].lower()
    arg = parts[1].strip() if len(parts) > 1 else ""
    known = name in COMMAND_NAMES or name in _HIDDEN_KNOWN
    return SlashCommand(name=name, arg=arg, known=known)
