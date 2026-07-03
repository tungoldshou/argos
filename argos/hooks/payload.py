from __future__ import annotations

import re
from typing import Any

from argos import tools as _tools  # get_tool_names

_TOOL_NAME_PATTERNS: dict[str, re.Pattern[str]] = {
    name: re.compile(rf"\b{re.escape(name)}\(")
    for name in _tools.get_tool_names()
}


def extract_tool_names(code: str) -> list[str]:
    if not code:
        return []
    seen: set[str] = set()
    result: list[str] = []
    for name, pat in _TOOL_NAME_PATTERNS.items():
        if pat.search(code) and name not in seen:
            seen.add(name)
            result.append(name)
    return result


def render_command(command: str, **kwargs: Any) -> str:
    safe = {k: v for k, v in kwargs.items() if v is not None}
    if "tool_names" in safe and isinstance(safe["tool_names"], list):
        safe["tool_names"] = ",".join(safe["tool_names"])

    def _sub(m: "re.Match[str]") -> str:
        key = m.group(1)
        if key in safe:
            return str(safe[key])
        return m.group(0)

    return re.sub(r"(?<!\{)\{([a-zA-Z_][a-zA-Z0-9_]*)\}(?!\})", _sub, command)



def build_pre_payload(
    *, session_id: str, cwd: str, code: str, tool_names: list[str],
) -> dict[str, Any]:
    return {
        "hook_event_name": "PreToolUse",
        "session_id": session_id,
        "cwd": cwd,
        "code": code,
        "tool_names": tool_names,
    }


def build_post_payload(
    *, session_id: str, cwd: str, code: str, tool_names: list[str],
    stdout: str, value_repr: str, exc: str, ok: bool,
) -> dict[str, Any]:
    return {
        "hook_event_name": "PostToolUse",
        "session_id": session_id,
        "cwd": cwd,
        "code": code,
        "tool_names": tool_names,
        "stdout": stdout,
        "value_repr": value_repr,
        "exc": exc,
        "ok": ok,
    }


def build_stop_payload(
    *, session_id: str, cwd: str, goal: str,
    verdict_status: str, actions: int, elapsed_s: float, escalated: bool,
) -> dict[str, Any]:
    return {
        "hook_event_name": "Stop",
        "session_id": session_id,
        "cwd": cwd,
        "goal": goal,
        "verdict_status": verdict_status,
        "actions": actions,
        "elapsed_s": elapsed_s,
        "escalated": escalated,
    }


def build_user_prompt_payload(
    *, session_id: str, cwd: str, goal: str,
) -> dict[str, Any]:
    return {
        "hook_event_name": "UserPromptSubmit",
        "session_id": session_id,
        "cwd": cwd,
        "goal": goal,
    }


def build_session_start_payload(
    *, session_id: str, cwd: str, model_tier: str,
) -> dict[str, Any]:
    return {
        "hook_event_name": "SessionStart",
        "session_id": session_id,
        "cwd": cwd,
        "model_tier": model_tier,
    }
