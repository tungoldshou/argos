# tests/tui/test_activity_panel.py
"""Regression tests for activity_panel design-audit fixes (2026-06-14).

Covers the five audit findings applied to ActivityPanel:
  [HIGH]   Verdict 三态语义着色 — passed/$pass, failed/$fail,
           unverifiable/$unverif, self-verified/$pass-weak
  [MEDIUM] 缓存 sparkline 整行 $cyan 着色
  [MEDIUM] 上下文进度条 ▓→$eye / ░→$ink-ghost / pct%→$ink-dim
  [LOW]    TODO/phase 条目亮度分级(in_progress/$ink-bright,
           completed/$ink-dim, pending/$ink-faint)
  [LOW]    Token 计数千分缩写(↑12.4k ↓3.1k)

Tests operate on the widget in "headless" mode (no Textual app):
_render_* helpers and the _set(idx, body) path are exercised at the
data/Rich-Text level, not through the mounted DOM.  This matches the
pattern in tests/tui/test_trust_dial.py.
"""
from __future__ import annotations

import types
from dataclasses import dataclass

import pytest
from rich.text import Text

from argos.tui.widgets.activity_panel import (
    ActivityPanel,
    _COL_CYAN,
    _COL_EYE,
    _COL_FAIL,
    _COL_INK_BRIGHT,
    _COL_INK_DIM,
    _COL_INK_FAINT,
    _COL_INK_GHOST,
    _COL_PASS,
    _COL_PASS_WEAK,
    _COL_UNVERIF,
)


# ── helpers ──────────────────────────────────────────────────────────────────

def _plain(t: "str | Text") -> str:
    """Strip Rich styles — return plain text."""
    if isinstance(t, Text):
        return t.plain
    return str(t)


def _spans_with_style(t: Text, substring: str) -> list[str]:
    """Return list of style strings for spans whose text contains *substring*."""
    styles = []
    for span in t._spans:
        span_text = t.plain[span.start:span.end]
        if substring in span_text:
            styles.append(str(span.style))
    return styles


def _first_style_containing(t: Text, substring: str) -> str | None:
    """First span-style that covers *substring* in the Text, or None."""
    matches = _spans_with_style(t, substring)
    return matches[0] if matches else None


def _make_verdict(status: str, self_verified: bool = False,
                  verify_cmd: str = "make test",
                  detail: str = "ok") -> object:
    """Minimal duck-typed verdict object."""
    v = types.SimpleNamespace(
        status=status,
        self_verified=self_verified,
        verify_cmd=verify_cmd,
        detail=detail,
    )
    return v


# ── ActivityPanel headless fixture ───────────────────────────────────────────

@pytest.fixture()
def panel() -> ActivityPanel:
    """Construct ActivityPanel without mounting (no Textual app needed)."""
    return ActivityPanel(model_label="test-model", tier="default")


# ── [HIGH] Verdict 三态着色 ───────────────────────────────────────────────────

class TestVerdictColoring:
    """Verdict section must colour status word by state (三态铁律)."""

    def _get_verdict_rich(self, panel: ActivityPanel, verdict) -> "str | Text":
        """Call on_verdict and capture what _set receives."""
        captured: list["str | Text"] = []
        original_set = panel._set
        def _capturing_set(idx: int, body: "str | Text") -> None:  # noqa: ANN001
            if idx == panel._VERDICT_IDX:
                captured.append(body)
        panel._set = _capturing_set  # type: ignore[method-assign]
        panel.on_verdict(verdict)
        panel._set = original_set  # type: ignore[method-assign]
        return captured[0] if captured else Text()

    def test_passed_uses_pass_color(self, panel: ActivityPanel) -> None:
        rt = self._get_verdict_rich(panel, _make_verdict("passed"))
        assert isinstance(rt, Text), "on_verdict must emit Rich Text"
        assert "passed" in _plain(rt)
        style = _first_style_containing(rt, "passed")
        assert style is not None, "status span must have a style"
        assert _COL_PASS in style, f"passed must use $pass ({_COL_PASS}), got {style!r}"

    def test_failed_uses_fail_color(self, panel: ActivityPanel) -> None:
        rt = self._get_verdict_rich(panel, _make_verdict("failed"))
        assert isinstance(rt, Text)
        style = _first_style_containing(rt, "failed")
        assert style is not None
        assert _COL_FAIL in style, f"failed must use $fail ({_COL_FAIL}), got {style!r}"

    def test_unverifiable_uses_unverif_color(self, panel: ActivityPanel) -> None:
        rt = self._get_verdict_rich(panel, _make_verdict("unverifiable"))
        assert isinstance(rt, Text)
        style = _first_style_containing(rt, "unverifiable")
        assert style is not None
        assert _COL_UNVERIF in style, (
            f"unverifiable must use $unverif ({_COL_UNVERIF}), got {style!r}"
        )

    def test_self_verified_uses_pass_weak(self, panel: ActivityPanel) -> None:
        rt = self._get_verdict_rich(panel, _make_verdict("passed", self_verified=True))
        assert isinstance(rt, Text)
        # plain text must include "(self-verified)"
        assert "(self-verified)" in _plain(rt)
        style = _first_style_containing(rt, "passed")
        assert style is not None
        assert _COL_PASS_WEAK in style, (
            f"self-verified must use $pass-weak ({_COL_PASS_WEAK}), got {style!r}"
        )

    def test_passed_not_wrongly_fail_color(self, panel: ActivityPanel) -> None:
        rt = self._get_verdict_rich(panel, _make_verdict("passed"))
        style = _first_style_containing(rt, "passed")
        assert _COL_FAIL not in (style or ""), "passed must NOT be coloured $fail"
        assert _COL_UNVERIF not in (style or ""), "passed must NOT be coloured $unverif"

    def test_verdict_plain_text_preserved(self, panel: ActivityPanel) -> None:
        """Verify cmd and detail must still appear in plain text."""
        rt = self._get_verdict_rich(
            panel, _make_verdict("failed", verify_cmd="pytest -x", detail="2 failed")
        )
        plain = _plain(rt)
        assert "pytest -x" in plain
        assert "2 failed" in plain


# ── [MEDIUM] Cache sparkline $cyan ───────────────────────────────────────────

class TestCacheSparklineCyan:
    """cache sparkline line must be coloured $cyan."""

    def _get_cost_rich(self, panel: ActivityPanel, **kwargs) -> "str | Text":
        captured: list["str | Text"] = []
        original_set = panel._set
        def _capturing_set(idx: int, body: "str | Text") -> None:
            if idx == panel._COST_IDX:
                captured.append(body)
        panel._set = _capturing_set  # type: ignore[method-assign]
        defaults = dict(
            tokens_in=1000, tokens_out=200, cost_usd=0.005,
            elapsed_s=1.2, cache_read=512, tier_name="",
        )
        defaults.update(kwargs)
        panel.on_cost(**defaults)
        panel._set = original_set  # type: ignore[method-assign]
        return captured[0] if captured else Text()

    def test_sparkline_line_is_cyan(self, panel: ActivityPanel) -> None:
        # Pump multiple calls to build a non-empty sparkline history
        for cache_val in [256, 512, 1024, 2048]:
            rt = self._get_cost_rich(panel, cache_read=cache_val)
        assert isinstance(rt, Text), "on_cost must emit Rich Text"
        plain = _plain(rt)
        assert "cache" in plain, "sparkline line prefix 'cache' must appear"
        style = _first_style_containing(rt, "cache")
        assert style is not None, "sparkline span must carry a style"
        assert _COL_CYAN in style, (
            f"sparkline line must be $cyan ({_COL_CYAN}), got {style!r}"
        )

    def test_cost_line_still_present(self, panel: ActivityPanel) -> None:
        rt = self._get_cost_rich(panel, tokens_in=500, tokens_out=100,
                                 cost_usd=0.002, cache_read=0)
        plain = _plain(rt)
        assert "$0.002" in plain
        assert "↑" in plain and "↓" in plain


# ── [MEDIUM] Context progress bar colors ─────────────────────────────────────

class TestContextBarColors:
    """Progress bar: ▓→$eye, ░→$ink-ghost, pct%→$ink-dim."""

    def _get_ctx_rich(self, panel: ActivityPanel,
                      used: int = 34000, window: int = 100000) -> "str | Text":
        captured: list["str | Text"] = []
        original_set = panel._set
        def _capturing_set(idx: int, body: "str | Text") -> None:
            if idx == panel._CTX_IDX:
                captured.append(body)
        panel._set = _capturing_set  # type: ignore[method-assign]
        panel.on_context(used=used, window=window)
        panel._set = original_set  # type: ignore[method-assign]
        return captured[0] if captured else Text()

    def test_filled_bar_is_eye_color(self, panel: ActivityPanel) -> None:
        # 50% → 5 filled ▓ chars
        rt = self._get_ctx_rich(panel, used=50000, window=100000)
        assert isinstance(rt, Text)
        style = _first_style_containing(rt, "▓")
        assert style is not None, "▓ span must carry a style"
        assert _COL_EYE in style, f"▓ must be $eye ({_COL_EYE}), got {style!r}"

    def test_empty_bar_is_ink_ghost(self, panel: ActivityPanel) -> None:
        rt = self._get_ctx_rich(panel, used=10000, window=100000)
        assert isinstance(rt, Text)
        style = _first_style_containing(rt, "░")
        assert style is not None, "░ span must carry a style"
        assert _COL_INK_GHOST in style, (
            f"░ must be $ink-ghost ({_COL_INK_GHOST}), got {style!r}"
        )

    def test_pct_label_is_ink_dim(self, panel: ActivityPanel) -> None:
        rt = self._get_ctx_rich(panel, used=34000, window=100000)
        assert isinstance(rt, Text)
        plain = _plain(rt)
        assert "%" in plain
        style = _first_style_containing(rt, "%")
        assert style is not None, "pct% span must carry a style"
        assert _COL_INK_DIM in style, (
            f"pct% must be $ink-dim ({_COL_INK_DIM}), got {style!r}"
        )

    def test_badge_in_plain_text(self, panel: ActivityPanel) -> None:
        rt = self._get_ctx_rich(panel, used=34000, window=100000)
        assert "[ctx" in _plain(rt)


# ── [LOW] TODO / phase brightness levels ─────────────────────────────────────

class TestTodoBrightnessLevels:
    """TODO items: in_progress/$ink-bright, completed/$ink-dim, pending/$ink-faint."""

    def test_in_progress_todo_is_ink_bright(self, panel: ActivityPanel) -> None:
        panel._todos = [{"status": "in_progress", "content": "write tests",
                          "activeForm": "writing tests now"}]
        rt = panel._render_todos()
        assert isinstance(rt, Text)
        assert "◉" in _plain(rt)
        style = _first_style_containing(rt, "◉")
        assert style is not None
        assert _COL_INK_BRIGHT in style, (
            f"in_progress must be $ink-bright ({_COL_INK_BRIGHT}), got {style!r}"
        )

    def test_completed_todo_is_ink_dim(self, panel: ActivityPanel) -> None:
        panel._todos = [{"status": "completed", "content": "done task"}]
        rt = panel._render_todos()
        assert isinstance(rt, Text)
        assert "◕" in _plain(rt)
        style = _first_style_containing(rt, "◕")
        assert style is not None
        assert _COL_INK_DIM in style, (
            f"completed must be $ink-dim ({_COL_INK_DIM}), got {style!r}"
        )

    def test_pending_todo_is_ink_faint(self, panel: ActivityPanel) -> None:
        panel._todos = [{"status": "pending", "content": "future task"}]
        rt = panel._render_todos()
        assert isinstance(rt, Text)
        assert "◌" in _plain(rt)
        style = _first_style_containing(rt, "◌")
        assert style is not None
        assert _COL_INK_FAINT in style, (
            f"pending must be $ink-faint ({_COL_INK_FAINT}), got {style!r}"
        )

    def test_todo_glyph_correctness(self, panel: ActivityPanel) -> None:
        """Glyph cross-wire guard: ◓ must NEVER appear in TODO output."""
        panel._todos = [
            {"status": "completed", "content": "a"},
            {"status": "in_progress", "content": "b"},
            {"status": "pending", "content": "c"},
        ]
        plain = _plain(panel._render_todos())
        assert "◓" not in plain, "◓ (blocked-only) must never appear in TODO output"


class TestPhaseBrightnessLevels:
    """Phase rows: in-progress (›)→$ink-bright, completed (✓)→$ink-dim."""

    def test_active_phase_is_ink_bright(self, panel: ActivityPanel) -> None:
        panel._phases = [("plan", 0.0, "›")]
        rt = panel._render_phases()
        assert isinstance(rt, Text)
        assert "◔" in _plain(rt)
        style = _first_style_containing(rt, "◔")
        assert style is not None
        assert _COL_INK_BRIGHT in style, (
            f"active phase must be $ink-bright ({_COL_INK_BRIGHT}), got {style!r}"
        )

    def test_completed_phase_is_ink_dim(self, panel: ActivityPanel) -> None:
        panel._phases = [("plan", 2.3, "✓")]
        rt = panel._render_phases()
        assert isinstance(rt, Text)
        assert "◔" in _plain(rt)
        style = _first_style_containing(rt, "◔")
        assert style is not None
        assert _COL_INK_DIM in style, (
            f"completed phase must be $ink-dim ({_COL_INK_DIM}), got {style!r}"
        )

    def test_phase_glyph_correctness(self, panel: ActivityPanel) -> None:
        """Glyph dictionary guard: plan=◔ act=◉ verify=❂ report=◕, ◓ never appears."""
        panel._phases = [
            ("plan", 1.0, "✓"),
            ("act", 0.0, "›"),
            ("verify", 0.0, "›"),
        ]
        plain = _plain(panel._render_phases())
        assert "◔" in plain, "plan phase must use ◔"
        assert "◉" in plain, "act phase must use ◉"
        assert "❂" in plain, "verify phase must use ❂"
        assert "◓" not in plain, "◓ (blocked-only) must never appear in phase output"

    def test_empty_phases_returns_string(self, panel: ActivityPanel) -> None:
        panel._phases = []
        result = panel._render_phases()
        assert isinstance(result, str)
        assert result == "(待开始)"


# ── [LOW] Token k-abbreviation ───────────────────────────────────────────────

class TestTokenKAbbreviation:
    """tokens_in/tokens_out ≥1000 must render as '{n/1000:.1f}k'."""

    def test_fmt_tokens_below_1000(self, panel: ActivityPanel) -> None:
        assert panel._fmt_tokens(0) == "0"
        assert panel._fmt_tokens(999) == "999"
        assert panel._fmt_tokens(500) == "500"

    def test_fmt_tokens_at_1000(self, panel: ActivityPanel) -> None:
        assert panel._fmt_tokens(1000) == "1.0k"

    def test_fmt_tokens_large(self, panel: ActivityPanel) -> None:
        assert panel._fmt_tokens(12400) == "12.4k"
        assert panel._fmt_tokens(3100) == "3.1k"

    def test_cost_display_uses_k_abbrev(self, panel: ActivityPanel) -> None:
        """on_cost with tokens_in=12400, tokens_out=3100 must show ↑12.4k ↓3.1k."""
        captured: list["str | Text"] = []
        original_set = panel._set
        def _capturing_set(idx: int, body: "str | Text") -> None:
            if idx == panel._COST_IDX:
                captured.append(body)
        panel._set = _capturing_set  # type: ignore[method-assign]
        panel.on_cost(tokens_in=12400, tokens_out=3100, cost_usd=0.010,
                      elapsed_s=2.5, cache_read=0)
        panel._set = original_set  # type: ignore[method-assign]
        assert captured, "on_cost must call _set"
        plain = _plain(captured[0])
        assert "↑12.4k" in plain, f"Expected ↑12.4k in {plain!r}"
        assert "↓3.1k" in plain, f"Expected ↓3.1k in {plain!r}"

    def test_small_tokens_not_abbreviated(self, panel: ActivityPanel) -> None:
        captured: list["str | Text"] = []
        original_set = panel._set
        def _capturing_set(idx: int, body: "str | Text") -> None:
            if idx == panel._COST_IDX:
                captured.append(body)
        panel._set = _capturing_set  # type: ignore[method-assign]
        panel.on_cost(tokens_in=50, tokens_out=20, cost_usd=0.001,
                      elapsed_s=0.5, cache_read=0)
        panel._set = original_set  # type: ignore[method-assign]
        plain = _plain(captured[0])
        assert "↑50" in plain
        assert "↓20" in plain
