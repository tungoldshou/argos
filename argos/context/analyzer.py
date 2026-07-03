from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from argos.context.tokens import token_estimate

if TYPE_CHECKING:
    from argos.core.loop import AgentLoop


@dataclass(frozen=True, slots=True)
class ContextBucket:
    name: str
    tokens: int
    entries: int
    source: str
    method: str           # "api" | "estimate:chars4" | "estimate:tiktoken" | "unavailable"
    details: tuple[tuple[str, int], ...] = ()


@dataclass(frozen=True, slots=True)
class ContextBreakdown:
    system: ContextBucket
    memory: ContextBucket
    tools: ContextBucket
    messages: ContextBucket
    total: int
    window: int
    pct: float
    method: str

    @property
    def health(self) -> str:
        if self.pct < 0.5:
            return "green"
        if self.pct < 0.8:
            return "yellow"
        return "red"


class ContextAnalyzer:

    @staticmethod
    def analyze(loop: "AgentLoop", *, store: Any, workspace: Path,
                goal: str | None = None) -> ContextBreakdown:
        return analyze(loop, store=store, workspace=workspace, goal=goal)


def _safe_system(loop: Any) -> ContextBucket:
    try:
        text = loop._build_system(goal_for_system(loop))  # type: ignore[attr-defined]
        tok, method = token_estimate(text)
        return ContextBucket("system", tok, 1, "core/loop.py:471", method)
    except Exception:  # noqa: BLE001
        return ContextBucket("system", 0, 0, "core/loop.py:471", "estimate:unavailable")


def goal_for_system(_loop: Any) -> str:
    return ""


def _safe_memory() -> ContextBucket:
    try:
        from argos.memory import auto as _auto  # type: ignore[import-not-found]
        scopes: tuple[tuple[str, str], ...] = (
            ("user", "user"), ("project", "project"),
            ("skill", "skill"), ("session", "session"),
        )
        details: list[tuple[str, int]] = []
        total = 0
        for name, scope in scopes:
            try:
                entries = _auto.load(scope=scope)  # type: ignore[arg-defined]
            except Exception:  # noqa: BLE001
                entries = []
            txt = "\n".join(getattr(e, "value", "") or "" for e in entries)
            tok, _ = token_estimate(txt)
            details.append((name, tok))
            total += tok
        return ContextBucket("memory", total, 4, "memory/auto.py:82",
                              "estimate:chars4",
                              details=tuple(details))
    except Exception:  # noqa: BLE001
        return ContextBucket("memory", 0, 0, "memory/auto.py:82", "estimate:unavailable",
                              details=(("user", 0), ("project", 0),
                                       ("skill", 0), ("session", 0)))


def _safe_tools(loop: Any) -> ContextBucket:
    try:
        text = loop._tool_signatures_block()  # type: ignore[attr-defined]
        tok, method = token_estimate(text)
        return ContextBucket("tools", tok, 22, "core/loop.py:430", method)
    except Exception:  # noqa: BLE001
        return ContextBucket("tools", 0, 0, "core/loop.py:430", "estimate:unavailable")


def _safe_messages(loop: Any, store: Any) -> ContextBucket:
    try:
        msgs = store.get_messages("") if hasattr(store, "get_messages") else []  # type: ignore[attr-defined]
    except Exception:  # noqa: BLE001
        msgs = []
    try:
        usage = getattr(loop._model, "last_usage", None) or {}  # type: ignore[attr-defined]
        tok = (int(usage.get("input_tokens") or 0)
               + int(usage.get("cache_read") or 0)
               + int(usage.get("cache_creation") or 0))
    except Exception:  # noqa: BLE001
        tok = 0
    method = "api" if tok else "api:unavailable"
    return ContextBucket("messages", tok, len(msgs), "memory/store.py:259", method)


def _safe_window(loop: Any) -> int:
    try:
        cw = loop._model.tier.context_window  # type: ignore[attr-defined]
        return int(cw) if cw and cw > 0 else 200_000
    except Exception:  # noqa: BLE001
        return 200_000


def analyze(loop: "AgentLoop", *, store: Any, workspace: Path,
            goal: str | None = None) -> ContextBreakdown:
    system = _safe_system(loop)
    memory = _safe_memory()
    tools = _safe_tools(loop)
    messages = _safe_messages(loop, store)
    window = _safe_window(loop)
    total = system.tokens + memory.tokens + tools.tokens + messages.tokens
    pct = total / window if window else 0.0
    return ContextBreakdown(system, memory, tools, messages, total, window, pct, "api+estimate")
