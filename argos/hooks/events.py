"""Internal documentation."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class HookFired:
    """Internal documentation."""
    event_name: str            # PreToolUse / PostToolUse / ...
    command: str
    success: bool
    returncode: int | None
    elapsed_ms: int
    timed_out: bool = False
    not_found: bool = False
    stop_reason: str | None = None
    error: str | None = None
    stdout: str = ""

    kind = "hook_fired"
