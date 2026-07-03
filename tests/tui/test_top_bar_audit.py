# tests/tui/test_top_bar_audit.py
"""Internal documentation."""
from __future__ import annotations

import pytest

from argos.tui.widgets.top_bar import (
    TopBar,
    _PHASE_GLYPH,
    _EYE_SOFT,
    _EYE,
    _UNVERIF,
    _FAIL,
    _PASS,
    _PLAN,
)


# ─────────────────────────────────────────────────────────────────────────────
# helpers
# ─────────────────────────────────────────────────────────────────────────────

def _bar(**kwargs) -> TopBar:
    """Internal documentation."""
    return TopBar(**kwargs)


# ─────────────────────────────────────────────────────────────────────────────
# ─────────────────────────────────────────────────────────────────────────────

class TestBlockedPhase:
    """Internal documentation."""

    def test_blocked_glyph_in_dict(self) -> None:
        """_PHASE_GLYPH['blocked'] == '◓' (U+25D3)。"""
        assert "blocked" in _PHASE_GLYPH, "'blocked' key missing from _PHASE_GLYPH"
        assert _PHASE_GLYPH["blocked"] == "◓", (
            f"blocked glyph should be ◓, got {_PHASE_GLYPH['blocked']!r}"
        )

    def test_blocked_glyph_in_render(self) -> None:
        """Internal documentation."""
        bar = _bar()
        bar.set_phase("blocked")
        text = bar.render_text
        assert "◓" in text, f"◓ not in render_text after set_phase('blocked'): {text!r}"
        assert "◌" not in text, (
            f"◌ (idle glyph) must not appear when phase=blocked: {text!r}"
        )

    def test_blocked_eye_color_is_unverif(self) -> None:
        """Internal documentation."""
        bar = _bar()
        bar.set_phase("blocked")
        rendered = bar.render()
        eye_span_style = rendered._spans[0].style if rendered._spans else ""
        assert _UNVERIF in str(eye_span_style), (
            f"blocked eye span style should contain {_UNVERIF}, got {eye_span_style!r}"
        )
        assert _EYE_SOFT not in str(eye_span_style), (
            f"blocked eye must not be $eye-soft {_EYE_SOFT}"
        )

    def test_idle_still_uses_eye_soft(self) -> None:
        """Internal documentation."""
        bar = _bar()
        bar.set_phase("idle")
        rendered = bar.render()
        eye_span_style = rendered._spans[0].style if rendered._spans else ""
        assert _EYE_SOFT in str(eye_span_style), (
            f"idle eye should be $eye-soft {_EYE_SOFT}, got {eye_span_style!r}"
        )

    def test_act_phase_uses_eye(self) -> None:
        """Internal documentation."""
        bar = _bar()
        bar.set_phase("act")
        rendered = bar.render()
        eye_span_style = rendered._spans[0].style if rendered._spans else ""
        assert _EYE in str(eye_span_style), (
            f"act eye should be $eye {_EYE}, got {eye_span_style!r}"
        )


# ─────────────────────────────────────────────────────────────────────────────
# ─────────────────────────────────────────────────────────────────────────────

class TestTrustBadgePresence:
    """Internal documentation."""

    def test_no_trust_badge_by_default(self) -> None:
        """Internal documentation."""
        bar = _bar()
        bar.set_state(has_key=True)
        bs = bar.badges()
        import re
        trust_badges = [b for b in bs if re.match(r"^(⏻ )?L\d", b)]
        assert trust_badges == [], f"unexpected trust badge(s) in default state: {trust_badges}"

    def test_trust_l1_badge_text(self) -> None:
        """Internal documentation."""
        bar = _bar()
        bar.set_state(has_key=True, trust_level=1, trust_label="只有危险操作才问")
        bs = bar.badges()
        assert "L1 · 只有危险操作才问" in bs, f"badges()={bs}"

    def test_trust_badge_is_last(self) -> None:
        """Internal documentation."""
        bar = _bar()
        bar.set_state(has_key=True, plan_mode=True, trust_level=2, trust_label="foo")
        bs = bar.badges()
        assert bs[-1].startswith("L2"), f"Trust badge must be last: {bs}"

    def test_trust_badge_after_live(self) -> None:
        """Internal documentation."""
        import re
        bar = _bar()
        bar.set_state(has_key=True, trust_level=0, trust_label="全自动")
        bs = bar.badges()
        live_idx = next((i for i, b in enumerate(bs) if b == "LIVE"), None)
        trust_idx = next((i for i, b in enumerate(bs) if re.match(r"^(⏻ )?L\d", b)), None)
        assert live_idx is not None, f"LIVE missing from badges: {bs}"
        assert trust_idx is not None, f"Trust badge missing from badges: {bs}"
        assert trust_idx > live_idx, (
            f"Trust badge must come after LIVE: live_idx={live_idx}, trust_idx={trust_idx}, badges={bs}"
        )

    def test_trust_l4_prefix(self) -> None:
        """Internal documentation."""
        bar = _bar()
        bar.set_state(has_key=True, trust_level=4, trust_label="每步都问")
        bs = bar.badges()
        trust_badge = next((b for b in bs if "L4" in b), None)
        assert trust_badge is not None, f"L4 trust badge missing: {bs}"
        assert trust_badge.startswith("⏻ "), (
            f"L4 badge must start with '⏻ ', got {trust_badge!r}"
        )

    def test_trust_without_label(self) -> None:
        """Internal documentation."""
        bar = _bar()
        bar.set_state(has_key=True, trust_level=3)
        bs = bar.badges()
        trust_badge = next((b for b in bs if "L3" in b), None)
        assert trust_badge is not None, f"L3 badge missing: {bs}"
        assert " · " not in trust_badge, (
            f"badge without label must not contain ' · ': {trust_badge!r}"
        )

    def test_trust_badge_in_render_text(self) -> None:
        """Internal documentation."""
        bar = _bar()
        bar.set_state(has_key=True, trust_level=2, trust_label="谨慎")
        text = bar.render_text
        assert "L2" in text, f"L2 not in render_text: {text!r}"
        assert "谨慎" in text, f"trust_label not in render_text: {text!r}"


# ─────────────────────────────────────────────────────────────────────────────
# ─────────────────────────────────────────────────────────────────────────────

class TestTrustBadgeColor:
    """Internal documentation."""

    @pytest.mark.parametrize("level", [0, 1, 2, 3])
    def test_trust_l0_l3_style_is_eye_soft(self, level: int) -> None:
        """Internal documentation."""
        bar = _bar()
        bar.set_state(has_key=True, trust_level=level, trust_label="test")
        bs = bar.badges()
        trust_badge = next(b for b in bs if f"L{level}" in b)
        style = bar._badge_style(trust_badge)
        assert style == _EYE_SOFT, (
            f"L{level} badge style should be $eye-soft {_EYE_SOFT!r}, got {style!r}"
        )

    def test_trust_l4_style_is_fail(self) -> None:
        """Internal documentation."""
        bar = _bar()
        bar.set_state(has_key=True, trust_level=4, trust_label="每步都问")
        bs = bar.badges()
        trust_badge = next(b for b in bs if "L4" in b)
        style = bar._badge_style(trust_badge)
        assert style == _FAIL, (
            f"L4 badge style should be $fail {_FAIL!r}, got {style!r}"
        )

    def test_live_badge_style_unchanged(self) -> None:
        """Internal documentation."""
        bar = _bar()
        bar.set_state(has_key=True, trust_level=1)
        assert bar._badge_style("LIVE") == _PASS

    def test_yolo_badge_style_unchanged(self) -> None:
        """Internal documentation."""
        bar = _bar()
        assert bar._badge_style("YOLO") == _FAIL

    def test_plan_badge_style_unchanged(self) -> None:
        """Internal documentation."""
        bar = _bar()
        assert bar._badge_style("plan") == _PLAN


# ─────────────────────────────────────────────────────────────────────────────
# ─────────────────────────────────────────────────────────────────────────────

class TestExistingContractLocked:
    """Internal documentation."""

    @pytest.mark.parametrize("phase,glyph", [
        ("idle",   "◌"),
        ("plan",   "◔"),
        ("act",    "◉"),
        ("verify", "❂"),
        ("report", "◕"),
        ("done",   "◕"),
    ])
    def test_original_glyphs_intact(self, phase: str, glyph: str) -> None:
        """Internal documentation."""
        assert _PHASE_GLYPH.get(phase) == glyph, (
            f"phase={phase!r} glyph changed: expected {glyph!r}, got {_PHASE_GLYPH.get(phase)!r}"
        )

    def test_has_key_false_no_live(self) -> None:
        """Internal documentation."""
        bar = _bar()
        bar.set_state(has_key=False)
        assert "LIVE" not in bar.badges(), "LIVE must never appear when has_key=False"

    def test_no_key_no_demo_shows_no_key_badge(self) -> None:
        """Internal documentation."""
        bar = _bar()
        bar.set_state(has_key=False)
        assert "未配 key" in bar.badges()

    def test_plan_mode_badge(self) -> None:
        """Internal documentation."""
        bar = _bar()
        bar.set_state(plan_mode=True)
        assert bar.badges()[0] == "plan"

    def test_yolo_badge(self) -> None:
        """Internal documentation."""
        bar = _bar()
        bar.set_state(yolo=True)
        assert "YOLO" in bar.badges()

    def test_unknown_phase_falls_back_to_idle_glyph(self) -> None:
        """Internal documentation."""
        bar = _bar()
        bar.set_phase("totally_unknown")
        text = bar.render_text
        assert "◌" in text, f"unknown phase should fall back to ◌: {text!r}"

    def test_render_text_contains_brand(self) -> None:
        """Internal documentation."""
        bar = _bar()
        assert "Argos" in bar.render_text

    def test_set_state_partial_update(self) -> None:
        """Internal documentation."""
        bar = _bar()
        bar.set_state(yolo=True)
        bar.set_state(plan_mode=True)
        assert "YOLO" in bar.badges(), "yolo should persist after partial set_state"
        assert "plan" in bar.badges(), "plan should appear after second set_state"


# ─────────────────────────────────────────────────────────────────────────────
# ─────────────────────────────────────────────────────────────────────────────

class TestBackgroundToken:
    """Internal documentation."""

    def test_default_css_has_background_surface(self) -> None:
        """Internal documentation."""
        assert "$surface" in TopBar.DEFAULT_CSS, (
            "DEFAULT_CSS must reference $surface (Textual slot = $well value)"
        )

    def test_default_css_has_well_comment(self) -> None:
        """Internal documentation."""
        assert "$well" in TopBar.DEFAULT_CSS, (
            "DEFAULT_CSS comment must mention $well to document the equivalence"
        )
