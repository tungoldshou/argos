from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from argos.i18n import t

DEFAULT_COMMAND_NAMES: tuple[str, ...] = (
    "help", "setup", "model", "status", "trust", "tools", "plan", "undo",
    "retry", "context", "permissions", "verify", "runs", "clear", "resume",
    "cost",
)

ADVANCED_COMMAND_NAMES: tuple[str, ...] = (
    "voice", "skills", "mcp", "hooks", "lsp", "orders", "confirm", "dismiss",
    "dream", "security-review", "simplify", "eval", "routing", "loop", "goal",
    "schedule", "watch", "ledger", "journal", "yolo",
)

_COMMAND_KEYS: tuple[str, ...] = DEFAULT_COMMAND_NAMES + ADVANCED_COMMAND_NAMES


def _build_command_help(names: Iterable[str] | None = None) -> dict[str, str]:
    keys = _COMMAND_KEYS if names is None else names
    return {name: t(f"cmd.{name}") for name in keys}


COMMAND_HELP: dict[str, str] = _build_command_help()

COMMAND_NAMES: list[str] = list(COMMAND_HELP)

_HIDDEN_KNOWN: frozenset[str] = frozenset({"remember", "forget", "memory"})


def match_commands(text: str) -> list[tuple[str, str]]:
    s = text.lstrip()
    if not s.startswith("/"):
        return []
    body = s[1:]
    if " " in body:
        return []
    pref = body.lower()
    command_help = _build_command_help(DEFAULT_COMMAND_NAMES)
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
