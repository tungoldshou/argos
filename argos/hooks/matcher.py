from __future__ import annotations

import re
from typing import Iterable

from argos.hooks.config import (
    HookHandler,
    HookMatcherEntry,
    HooksConfig,
    HooksConfigError,
)
from argos.i18n import t

_MATCHER_USED_EVENTS: frozenset[str] = frozenset({"PreToolUse", "PostToolUse"})

MAX_MATCHER_LENGTH: int = 256

_NESTED_QUANTIFIER_RE: re.Pattern[str] = re.compile(
    r"\([^)]*[+*][^)]*\)\s*[+*]"
)


def validate_matcher(matcher: str) -> None:
    if len(matcher) > MAX_MATCHER_LENGTH:
        raise HooksConfigError(
            t("hooks.matcher.too_long", length=len(matcher), limit=MAX_MATCHER_LENGTH)
        )
    if _NESTED_QUANTIFIER_RE.search(matcher):
        raise HooksConfigError(
            t("hooks.matcher.nested_quantifiers", matcher=matcher)
        )
    try:
        re.compile(matcher)
    except re.error as e:
        raise HooksConfigError(
            t("hooks.matcher.compile_error", matcher=matcher, exc=e)
        ) from e


def _matcher_hits(matcher: str | None, tool_names: Iterable[str]) -> bool:
    if matcher is None or matcher == "" or matcher == "*":
        return True
    try:
        pat = re.compile(matcher)
    except re.error:
        return False
    return any(pat.search(name) for name in tool_names)


def match(
    event_name: str,
    tool_names: Iterable[str],
    config: HooksConfig,
) -> list[HookHandler]:
    entries = config.entries.get(event_name, ())
    use_matcher = event_name in _MATCHER_USED_EVENTS
    seen_commands: set[str] = set()
    result: list[HookHandler] = []
    tool_list = list(tool_names)
    for entry in entries:
        if use_matcher and not _matcher_hits(entry.matcher, tool_list):
            continue
        for h in entry.hooks:
            if h.command in seen_commands:
                continue
            seen_commands.add(h.command)
            result.append(h)
    return result
