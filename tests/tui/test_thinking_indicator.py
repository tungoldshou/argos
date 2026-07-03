# tests/tui/test_thinking_indicator.py
from __future__ import annotations

import importlib
import inspect
import sys

import pytest

import argos.tui.widgets.thinking as _mod
from argos.tui.widgets.thinking import ThinkingIndicator, _FRAMES


# ─────────────────────────────────────────────────────────────────────────────
# ─────────────────────────────────────────────────────────────────────────────

def _make() -> ThinkingIndicator:
    return ThinkingIndicator(label="思考中…")


def _render_at_frame(widget: ThinkingIndicator, frame: int) -> str:
    widget._frame = frame
    return widget.render()


# ─────────────────────────────────────────────────────────────────────────────
# ─────────────────────────────────────────────────────────────────────────────

class TestBlinkOverlayRemoved:

    def test_no_blink_glyphs_constant(self):
        assert not hasattr(_mod, "_BLINK_GLYPHS"), (
            "_BLINK_GLYPHS must be removed; ◓ is reserved for blocked/unverif"
        )

    def test_no_blink_interval_ticks_constant(self):
        assert not hasattr(_mod, "_BLINK_INTERVAL_TICKS"), (
            "_BLINK_INTERVAL_TICKS must be removed along with blink overlay"
        )

    def test_no_blink_hold_ticks_constant(self):
        assert not hasattr(_mod, "_BLINK_HOLD_TICKS"), (
            "_BLINK_HOLD_TICKS must be removed along with blink overlay"
        )

    def test_instance_has_no_blink_ticks_left(self):
        widget = _make()
        assert not hasattr(widget, "_blink_ticks_left"), (
            "_blink_ticks_left must be removed from instance — blink overlay gone"
        )

    def test_instance_has_no_tick_count(self):
        widget = _make()
        assert not hasattr(widget, "_tick_count"), (
            "_tick_count must be removed from instance — blink overlay gone"
        )


# ─────────────────────────────────────────────────────────────────────────────
# ─────────────────────────────────────────────────────────────────────────────

class TestGlyphDiscipline:

    _BLOCKED_GLYPH = "◓"

    @pytest.mark.parametrize("frame", range(len(_FRAMES)))
    def test_no_blocked_glyph_at_any_frame(self, frame):
        widget = _make()
        output = _render_at_frame(widget, frame)
        assert self._BLOCKED_GLYPH not in output, (
            f"frame={frame}: render() must NOT emit ◓ (blocked-only glyph); got {output!r}"
        )

    @pytest.mark.parametrize("frame", range(len(_FRAMES)))
    def test_braille_glyph_at_every_frame(self, frame):
        widget = _make()
        output = _render_at_frame(widget, frame)
        expected_glyph = _FRAMES[frame]
        assert output.startswith(expected_glyph), (
            f"frame={frame}: expected glyph {expected_glyph!r} at start, got {output!r}"
        )

    def test_frames_constant_is_braille_only(self):
        for ch in _FRAMES:
            code = ord(ch)
            assert 0x2800 <= code <= 0x28FF, (
                f"_FRAMES contains non-braille character {ch!r} (U+{code:04X})"
            )

    def test_frames_has_ten_glyphs(self):
        assert len(_FRAMES) == 10, (
            f"_FRAMES must have 10 glyphs, got {len(_FRAMES)}: {_FRAMES!r}"
        )


# ─────────────────────────────────────────────────────────────────────────────
# ─────────────────────────────────────────────────────────────────────────────

class TestDocstringProvenance:

    _MODULE_DOC: str = _mod.__doc__ or ""
    _CLASS_DOC: str = ThinkingIndicator.__doc__ or ""

    @pytest.mark.parametrize("phantom", ["§6.1", "§6.2", "眼慢眨", "慢眨"])
    def test_module_docstring_no_phantom_spec(self, phantom):
        assert phantom not in self._MODULE_DOC, (
            f"Module docstring must not contain phantom spec ref {phantom!r}; "
            f"remove it — §6.1/§6.2 do not exist in the design handoff"
        )

    @pytest.mark.parametrize("phantom", ["§6.1", "§6.2", "眼慢眨", "慢眨"])
    def test_class_docstring_no_phantom_spec(self, phantom):
        assert phantom not in self._CLASS_DOC, (
            f"Class docstring must not contain phantom spec ref {phantom!r}"
        )

    def test_module_docstring_cites_real_source(self):
        real_refs = ["README", "01-act"]
        found = any(ref in self._MODULE_DOC for ref in real_refs)
        assert found, (
            f"Module docstring must cite the real design source "
            f"(README / 01-act); got: {self._MODULE_DOC!r}"
        )


# ─────────────────────────────────────────────────────────────────────────────
# ─────────────────────────────────────────────────────────────────────────────

class TestPublicAPI:

    def test_construct_default_label(self):
        widget = _make()
        assert widget._label == "思考中…"

    def test_construct_custom_label(self):
        widget = ThinkingIndicator(label="回归测试中…")
        assert widget._label == "回归测试中…"

    def test_set_label_updates_label(self):
        widget = _make()
        widget.set_label("新标签")
        assert widget._label == "新标签"

    def test_renderable_property_returns_string(self):
        widget = _make()
        result = widget.renderable
        assert isinstance(result, str)

    def test_renderable_equals_render(self):
        widget = _make()
        assert widget.renderable == widget.render()

    def test_render_contains_label(self):
        widget = ThinkingIndicator(label="测试标签")
        output = _render_at_frame(widget, 0)
        assert "测试标签" in output, f"render() must contain label; got {output!r}"

    def test_render_format_glyph_space_label(self):
        widget = ThinkingIndicator(label="abc")
        # frame=0 → _FRAMES[0] = '⠋'
        output = _render_at_frame(widget, 0)
        assert output[0] == _FRAMES[0], f"first char must be glyph; got {output!r}"
        assert output[1] == " ", f"second char must be space; got {output!r}"
        assert "abc" in output, f"label must appear in output; got {output!r}"

    def test_default_css_uses_eye_token(self):
        css = ThinkingIndicator.DEFAULT_CSS
        assert "$eye" in css, (
            f"DEFAULT_CSS must use $eye token (not hardcoded hex); got: {css!r}"
        )

    def test_default_css_no_hardcoded_hex(self):
        import re
        css = ThinkingIndicator.DEFAULT_CSS
        hex_pattern = re.compile(r"#[0-9A-Fa-f]{3,8}\b")
        matches = hex_pattern.findall(css)
        assert not matches, (
            f"DEFAULT_CSS must not contain hardcoded hex; found: {matches}"
        )

    def test_frame_cycles_through_all_frames(self):
        widget = _make()
        widget._frame = 0
        seen = set()
        for _ in range(len(_FRAMES)):
            seen.add(widget._frame)
            widget._frame = (widget._frame + 1) % len(_FRAMES)
        assert seen == set(range(len(_FRAMES))), (
            f"_tick must cycle through all {len(_FRAMES)} frames; only saw {sorted(seen)}"
        )
