"""#12 Context 可视化:4 桶分桶(契约 §12;spec §6)。

输入:loop 实例 + store + workspace + (可选)goal
输出:ContextBreakdown(4 桶 + total + window + pct + method + health)
任一桶失败降级(返 entries=0 tokens=0 + method=unavailable),不崩 run。"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from argos.context.tokens import token_estimate

if TYPE_CHECKING:
    from argos.core.loop import AgentLoop


@dataclass(frozen=True, slots=True)
class ContextBucket:
    """4 桶的通用形态(spec §4.1):name + tokens + entries + source + method + details。"""
    name: str
    tokens: int
    entries: int
    source: str           # 文件:行号,debug 用
    method: str           # "api" | "estimate:chars4" | "estimate:tiktoken" | "unavailable"
    details: tuple[tuple[str, int], ...] = ()


@dataclass(frozen=True, slots=True)
class ContextBreakdown:
    """聚合 4 桶 + 总 + 窗口 + 比例 + 健康色(spec §4.2)。"""
    system: ContextBucket
    memory: ContextBucket
    tools: ContextBucket
    messages: ContextBucket
    total: int
    window: int
    pct: float
    method: str           # 总体口径 "api+estimate"

    @property
    def health(self) -> str:
        """绿(<50%)/ 黄(50-80%)/ 红(>=80%)(spec §7.1)。"""
        if self.pct < 0.5:
            return "green"
        if self.pct < 0.8:
            return "yellow"
        return "red"


class ContextAnalyzer:
    """4 桶分析门面:实例化不绑 loop(便于测试 mock);调用 analyze() 时注入。"""

    @staticmethod
    def analyze(loop: "AgentLoop", *, store: Any, workspace: Path,
                goal: str | None = None) -> ContextBreakdown:
        return analyze(loop, store=store, workspace=workspace, goal=goal)


def _safe_system(loop: Any) -> ContextBucket:
    """system 桶(spec §6.1 step 1):走 _build_system。"""
    try:
        text = loop._build_system(goal_for_system(loop))  # type: ignore[attr-defined]
        tok, method = token_estimate(text)
        return ContextBucket("system", tok, 1, "core/loop.py:471", method)
    except Exception:  # noqa: BLE001
        return ContextBucket("system", 0, 0, "core/loop.py:471", "estimate:unavailable")


def goal_for_system(_loop: Any) -> str:
    """统一目标串(避免对 loop 实例做强假设;无 goal 即空串,不影响分桶)。"""
    return ""


def _safe_memory() -> ContextBucket:
    """memory 桶(spec §6.1 step 2 + D5):4 tier 各自 load → details。"""
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
    """tools 桶(spec §6.1 step 3):走 _tool_signatures_block;entries 估 22。"""
    try:
        text = loop._tool_signatures_block()  # type: ignore[attr-defined]
        tok, method = token_estimate(text)
        return ContextBucket("tools", tok, 22, "core/loop.py:430", method)
    except Exception:  # noqa: BLE001
        return ContextBucket("tools", 0, 0, "core/loop.py:430", "estimate:unavailable")


def _safe_messages(loop: Any, store: Any) -> ContextBucket:
    """messages 桶(spec §6.1 step 4):entries=len, tokens=API 真值。"""
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
    """window 来自 model.tier.context_window;fallback 200_000。"""
    try:
        cw = loop._model.tier.context_window  # type: ignore[attr-defined]
        return int(cw) if cw and cw > 0 else 200_000
    except Exception:  # noqa: BLE001
        return 200_000


def analyze(loop: "AgentLoop", *, store: Any, workspace: Path,
            goal: str | None = None) -> ContextBreakdown:
    """4 桶独立;任一失败降级(spec §6.1 + §13)。"""
    system = _safe_system(loop)
    memory = _safe_memory()
    tools = _safe_tools(loop)
    messages = _safe_messages(loop, store)
    window = _safe_window(loop)
    total = system.tokens + memory.tokens + tools.tokens + messages.tokens
    pct = total / window if window else 0.0
    return ContextBreakdown(system, memory, tools, messages, total, window, pct, "api+estimate")
