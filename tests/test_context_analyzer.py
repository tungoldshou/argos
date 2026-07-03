from __future__ import annotations

import sys
import types
from dataclasses import dataclass
from pathlib import Path

from argos.context.analyzer import (
    ContextAnalyzer,
    ContextBreakdown,
    ContextBucket,
    analyze,
)


@dataclass
class _FakeTier:
    context_window: int


@dataclass
class _FakeModel:
    tier: _FakeTier
    last_usage: dict = None  # type: ignore[assignment]

    def __post_init__(self):
        if self.last_usage is None:
            self.last_usage = {"input_tokens": 0, "output_tokens": 0,
                                "cache_read": 0, "cache_creation": 0}


@dataclass
class _FakeStore:
    msgs: list

    def get_messages(self, _sid: str) -> list:
        return list(self.msgs)


@dataclass
class _FakeLoop:
    _build_system_text: str = "sys"
    _tool_sigs_text: str = "tools"
    _model: _FakeModel = None  # type: ignore[assignment]
    store: _FakeStore = None  # type: ignore[assignment]

    def _build_system(self, _goal: str) -> str:
        return self._build_system_text

    def _tool_signatures_block(self) -> str:
        return self._tool_sigs_text


def _loop(*, sys_text="hello world", tool_text="abc", window=200_000,
          input_tokens=0, cache_read=0, cache_creation=0,
          msgs=None) -> _FakeLoop:
    model = _FakeModel(_FakeTier(context_window=window),
                       last_usage={"input_tokens": input_tokens, "output_tokens": 0,
                                   "cache_read": cache_read, "cache_creation": cache_creation})
    store = _FakeStore(msgs=msgs or [])
    return _FakeLoop(_build_system_text=sys_text, _tool_sigs_text=tool_text,
                     _model=model, store=store)


def test_analyze_four_buckets_independent(monkeypatch):
    loop = _loop(sys_text="will explode")

    def boom(_g):
        raise RuntimeError("nope")
    loop._build_system = boom  # type: ignore[assignment]
    b = analyze(loop, store=loop.store, workspace=Path("."))
    assert b.system.tokens == 0
    assert b.system.method == "estimate:unavailable"
    assert b.tools.tokens > 0 or b.tools.method == "estimate:unavailable"


def test_analyze_system_uses_build_system(monkeypatch):
    monkeypatch.setitem(sys.modules, "tiktoken", None)
    loop = _loop(sys_text="x" * 80)
    b = analyze(loop, store=loop.store, workspace=Path("."))
    assert b.system.tokens == 20
    assert b.system.source == "core/loop.py:471"
    assert b.system.method == "estimate:chars4"


def test_analyze_memory_loads_four_scopes(monkeypatch):
    # mock argos.memory.auto.load
    fake_auto = types.ModuleType("argos.memory.auto")

    def _fake_load(*, scope=None):
        return []
    fake_auto.load = _fake_load
    monkeypatch.setitem(sys.modules, "argos.memory.auto", fake_auto)

    loop = _loop()
    b = analyze(loop, store=loop.store, workspace=Path("."))
    assert b.memory.entries == 4
    assert b.memory.source == "memory/auto.py:82"
    names = [n for n, _ in b.memory.details]
    assert names == ["user", "project", "skill", "session"]


def test_analyze_tools_uses_signatures_block():
    loop = _loop(tool_text="read_file x y\nedit_file a b")
    b = analyze(loop, store=loop.store, workspace=Path("."))
    assert b.tools.tokens > 0
    assert b.tools.entries == 22
    assert b.tools.source == "core/loop.py:430"


def test_analyze_messages_uses_api_usage():
    loop = _loop(input_tokens=2000, cache_read=500, cache_creation=300,
                  msgs=[{"role": "user", "content": "x"}] * 5)
    b = analyze(loop, store=loop.store, workspace=Path("."))
    assert b.messages.tokens == 2800
    assert b.messages.entries == 5
    assert b.messages.method == "api"
    assert b.messages.source == "memory/store.py:259"


def test_analyze_window_fallback():
    """tier.context_window=0 → fallback 200_000。"""
    loop = _loop(window=0)
    b = analyze(loop, store=loop.store, workspace=Path("."))
    assert b.window == 200_000


def test_analyze_window_from_model():
    loop = _loop(window=8192)
    b = analyze(loop, store=loop.store, workspace=Path("."))
    assert b.window == 8192


def test_analyze_pct_calculation():
    loop = _loop(sys_text="x" * 4000, tool_text="y" * 1000, window=200_000)
    b = analyze(loop, store=loop.store, workspace=Path("."))
    assert 0.0 <= b.pct <= 1.0
    assert abs(b.pct - b.total / b.window) < 1e-9,\
        f"pct={b.pct} 应等于 total/window={b.total}/{b.window}"


def test_analyze_health_property():
    """pct<0.5 → green;0.5-0.8 → yellow;>=0.8 → red。"""
    b1 = ContextBreakdown(
        ContextBucket("s", 0, 0, "", "estimate:chars4"),
        ContextBucket("m", 0, 0, "", "estimate:chars4"),
        ContextBucket("t", 0, 0, "", "estimate:chars4"),
        ContextBucket("msg", 0, 0, "", "api"),
        total=40, window=100, pct=0.4, method="api+estimate")
    assert b1.health == "green"

    b2 = ContextBreakdown(
        ContextBucket("s", 0, 0, "", "estimate:chars4"),
        ContextBucket("m", 0, 0, "", "estimate:chars4"),
        ContextBucket("t", 0, 0, "", "estimate:chars4"),
        ContextBucket("msg", 0, 0, "", "api"),
        total=60, window=100, pct=0.6, method="api+estimate")
    assert b2.health == "yellow"

    b3 = ContextBreakdown(
        ContextBucket("s", 0, 0, "", "estimate:chars4"),
        ContextBucket("m", 0, 0, "", "estimate:chars4"),
        ContextBucket("t", 0, 0, "", "estimate:chars4"),
        ContextBucket("msg", 0, 0, "", "api"),
        total=90, window=100, pct=0.9, method="api+estimate")
    assert b3.health == "red"


def test_analyze_never_raises():
    class _BadLoop:
        @property
        def _model(self):
            raise RuntimeError("nope")

        def _build_system(self, _g):
            raise RuntimeError("nope")

        def _tool_signatures_block(self):
            raise RuntimeError("nope")

    class _BadStore:
        def get_messages(self, _s):
            raise RuntimeError("nope")

    b = analyze(_BadLoop(), store=_BadStore(), workspace=Path("."))  # type: ignore[arg-type]
    assert b.total >= 0
    assert b.window >= 0
    assert b.system.method == "estimate:unavailable"
    assert b.tools.method == "estimate:unavailable"
    assert b.messages.method == "api:unavailable"
