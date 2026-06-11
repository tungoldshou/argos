"""Payload 构造 + 工具名抽取 + 模板占位(spec §2.3 / §4.4 / D7 / D8)。

- `extract_tool_names(code)`:regex `\\b(name)\\(` 扫 `tools.ALL_TOOL_NAMES`,
  去重保 order;非已知 tool 忽略(防误报);无调用 → []。
- `build_*_payload(...)`:5 事件各产一个 dict(只含本事件相关字段,spec §2.3)。
- `render_command(cmd, **kw)`:str.format 单层占位替换 {cwd}/{session_id}/{tool_names};
  无模板时不依赖任何 kw(没用到也不抛 KeyError,因为我们手动 format 单层)。
"""
from __future__ import annotations

import re
from typing import Any

from argos_agent import tools as _tools  # get_tool_names

# 工具名 → 抽调用 regex(预编译 cache;spec D7 正则而非 AST)。
# P3：从 get_tool_names() 派生（退静态表路径；hooks 是无 registry 的 headless 场景）。
_TOOL_NAME_PATTERNS: dict[str, re.Pattern[str]] = {
    name: re.compile(rf"\b{re.escape(name)}\(")
    for name in _tools.get_tool_names()
}


def extract_tool_names(code: str) -> list[str]:
    """从 code 字符串中抽已注册的 tool 调用名(去重保 order)。

    实现:逐个 tool 名扫 regex `\\b(name)\\(`,命中即收。误报("字符串内含工具名")
    是审计偏紧,无害(spec D7)。
    """
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
    """单层占位替换(spec D8)。占位:{cwd} / {session_id} / {tool_names}。

    实现:re 找已知占位 → 替换;缺失占位 / 其他 `{...}` 字面保留(spec D8 _SafeDict)。
    不走 str.format_map(会被 JSON 字面 `{...}` 误判为 format spec 抛 ValueError)。
    """
    safe = {k: v for k, v in kwargs.items() if v is not None}
    # tool_names 列表 → 逗号拼接;其他原样
    if "tool_names" in safe and isinstance(safe["tool_names"], list):
        safe["tool_names"] = ",".join(safe["tool_names"])

    def _sub(m: "re.Match[str]") -> str:
        key = m.group(1)
        if key in safe:
            return str(safe[key])
        return m.group(0)   # 未知占位 → 保留原文(spec D8)

    # 单层占位,不是 `{{` / `}}`;负 lookbehind 防 matched `{{cwd}}`
    return re.sub(r"(?<!\{)\{([a-zA-Z_][a-zA-Z0-9_]*)\}(?!\})", _sub, command)


# ── 5 个 payload 构造器 ─────────────────────────────────────────────

def build_pre_payload(
    *, session_id: str, cwd: str, code: str, tool_names: list[str],
) -> dict[str, Any]:
    """PreToolUse payload(spec §2.3 表)。"""
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
    """PostToolUse payload(spec §2.3 表)。"""
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
    """Stop payload(spec §2.3 表)。"""
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
    """UserPromptSubmit payload(spec §2.3 表)。"""
    return {
        "hook_event_name": "UserPromptSubmit",
        "session_id": session_id,
        "cwd": cwd,
        "goal": goal,
    }


def build_session_start_payload(
    *, session_id: str, cwd: str, model_tier: str,
) -> dict[str, Any]:
    """SessionStart payload(spec §2.3 表)。"""
    return {
        "hook_event_name": "SessionStart",
        "session_id": session_id,
        "cwd": cwd,
        "model_tier": model_tier,
    }
