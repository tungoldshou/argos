# tests/tui/test_splash_design_audit.py
from __future__ import annotations

import re

import pytest

from argos.tui.widgets.splash import (
    StartupSplash,
    _compose_text,
    _COL_EYE_GLOW,
    _COL_INK_DIM,
    _COL_INK_FAINT,
    _COL_PASS,
    _COL_UNVERIF,
)


# ─────────────────────────────────────────────────────────────────────────────
# helpers
# ─────────────────────────────────────────────────────────────────────────────

def _text(**kw) -> str:
    defaults = dict(model_label="minimax-01", live=True, plan_mode=False, has_key=True, eye_stage="focus")
    defaults.update(kw)
    return _compose_text(**defaults)  # type: ignore[arg-type]


def _has_color_wrap(text: str, color: str, content: str) -> bool:
    pattern = re.escape(f"[{color}]") + r"[^[]*" + re.escape(content) + r"[^[]*" + re.escape(f"[/{color}]")
    return bool(re.search(pattern, text, re.DOTALL))


# ─────────────────────────────────────────────────────────────────────────────
# ─────────────────────────────────────────────────────────────────────────────

class TestComposeTextColorMarkup:

    def test_eye_glyph_wrapped_in_eye_glow(self) -> None:
        text = _text(eye_stage="focus")
        assert f"[{_COL_EYE_GLOW}]" in text, "eye markup opening tag missing"
        assert f"[/{_COL_EYE_GLOW}]" in text, "eye markup closing tag missing"
        assert _has_color_wrap(text, _COL_EYE_GLOW, "◉"), (
            f"◉ glyph not wrapped in {_COL_EYE_GLOW}"
        )

    def test_eye_glow_hex_matches_theme(self) -> None:
        assert _COL_EYE_GLOW == "#F0C078", f"Expected #F0C078, got {_COL_EYE_GLOW}"

    def test_live_badge_wrapped_in_pass(self) -> None:
        text = _text(live=True, has_key=True)
        assert _has_color_wrap(text, _COL_PASS, "LIVE"), (
            f"LIVE badge not wrapped in {_COL_PASS} ($pass)"
        )

    def test_pass_hex_matches_theme(self) -> None:
        assert _COL_PASS == "#9ECE6A", f"Expected #9ECE6A, got {_COL_PASS}"

    def test_unverif_hex_matches_theme(self) -> None:
        assert _COL_UNVERIF == "#FF9E64", f"Expected #FF9E64, got {_COL_UNVERIF}"

    def test_subtitle_line_wrapped_in_ink_dim(self) -> None:
        text = _text(live=True, has_key=True)
        assert f"[{_COL_INK_DIM}]" in text, f"ink-dim opening tag missing in text"
        assert "百眼智能体" in text, "subtitle word missing"
        assert _has_color_wrap(text, _COL_INK_DIM, "百眼智能体"), (
            f"subtitle not wrapped in {_COL_INK_DIM} ($ink-dim)"
        )

    def test_ink_dim_hex_matches_theme(self) -> None:
        assert _COL_INK_DIM == "#7E869C", f"Expected #7E869C, got {_COL_INK_DIM}"

    def test_hint_line_wrapped_in_ink_faint(self) -> None:
        text = _text()
        assert _has_color_wrap(text, _COL_INK_FAINT, "输入目标开始"), (
            f"hint line not wrapped in {_COL_INK_FAINT} ($ink-faint)"
        )

    def test_ink_faint_hex_matches_theme(self) -> None:
        assert _COL_INK_FAINT == "#6B7494", f"Expected #6B7494 (finding #27), got {_COL_INK_FAINT}"

    def test_no_key_badge_uses_ink_dim_not_pass(self) -> None:
        text = _text(live=True, has_key=False)
        assert "LIVE" not in text, "LIVE must not appear when has_key=False"
        assert _has_color_wrap(text, _COL_INK_DIM, "未配 key"), (
            f"no-key badge not wrapped in {_COL_INK_DIM}"
        )


# ─────────────────────────────────────────────────────────────────────────────
# ─────────────────────────────────────────────────────────────────────────────

class TestDefaultCssNoInkBright:

    def test_default_css_no_ink_bright_color(self) -> None:
        css = StartupSplash.DEFAULT_CSS
        assert "color: $ink-bright" not in css, (
            "DEFAULT_CSS must not contain 'color: $ink-bright' — "
            "per-segment markup handles coloring now"
        )

    def test_default_css_has_stream_background(self) -> None:
        css = StartupSplash.DEFAULT_CSS
        assert "$stream" in css, "DEFAULT_CSS must still set background: $stream"


# ─────────────────────────────────────────────────────────────────────────────
# ─────────────────────────────────────────────────────────────────────────────

class TestMarkupEnabled:

    def test_widget_render_markup_flag(self) -> None:
        w = StartupSplash(model_label="test-model", tier="default", live=True, has_key=True)
        assert w._render_markup is True, (
            "StartupSplash must be constructed with markup=True so Rich color tags are parsed"
        )

    def test_widget_demo_render_markup_flag(self) -> None:
        w = StartupSplash(model_label="fake-model", tier="default", live=False, has_key=True)
        assert w._render_markup is True


# ─────────────────────────────────────────────────────────────────────────────
# ─────────────────────────────────────────────────────────────────────────────

class TestFunctionalNonRegression:

    def test_argos_wordmark_still_in_renderable_text(self) -> None:
        w = StartupSplash(model_label="m", tier="t", live=True, has_key=True)
        assert "ARGOS" in w.renderable_text

    def test_plan_mode_prefix_present(self) -> None:
        text = _text(plan_mode=True)
        assert text.startswith("plan · "), f"plan mode prefix missing, text starts: {text[:40]!r}"

    def test_no_plan_mode_no_prefix(self) -> None:
        text = _text(plan_mode=False)
        assert not text.startswith("plan · ")

    def test_eye_stage_init_gives_idle_glyph(self) -> None:
        text = _text(live=True, has_key=True, eye_stage="init")
        assert _has_color_wrap(text, _COL_EYE_GLOW, "◌"), "init stage should show ◌ in eye-glow"

    def test_eye_stage_focus_gives_focus_glyph(self) -> None:
        text = _text(live=True, has_key=True, eye_stage="focus")
        assert _has_color_wrap(text, _COL_EYE_GLOW, "◉"), "focus stage should show ◉ in eye-glow"

    def test_no_key_eye_always_idle(self) -> None:
        for stage in ("init", "scan", "half", "focus", "open"):
            text = _text(live=True, has_key=False, eye_stage=stage)
            assert _has_color_wrap(text, _COL_EYE_GLOW, "◌"), (
                f"no-key: stage={stage!r} should still show ◌, not another glyph"
            )

    def test_advance_eye_updates_text(self) -> None:
        w = StartupSplash(model_label="m", tier="t", live=True, has_key=True)
        assert _has_color_wrap(w.renderable_text, _COL_EYE_GLOW, "◌")
        w.advance_eye("focus")
        assert _has_color_wrap(w.renderable_text, _COL_EYE_GLOW, "◉")

    def test_live_badge_not_without_key(self) -> None:
        w = StartupSplash(model_label="m", tier="t", live=True, has_key=False)
        assert "LIVE" not in w.renderable_text
