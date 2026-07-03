# tests/tui/test_prompt_audit.py
"""Regression tests for PromptArea + SlashMenu design-audit fixes (2026-06-14).

Covers:
  [MEDIUM] Slash 菜单选中行整行 $raise-2 底色块
           视觉稿 line 293 / README §126 §304 — 选中行(▸ + 命令名 + 描述)
           整体须带 bgcolor $raise-2 (#23263A).  以前的实现用死 CSS 规则
           (.menu-selected) 对无子-widget 的单个 Static 无效;
           fix: _render_items() 里对选中行的每段 Rich Style 直接注入 bgcolor.
  [LOW]    PromptArea border: tall $eye-soft drift (lives in app.py:116,
           NOT in prompt.py — noted in report, not code-patched here).

Tests operate headless (no mounted Textual app):
  - SlashMenu is instantiated directly.
  - show_matches() / move() / _render_items() are exercised at the
    Rich-Text level by monkey-patching update().
"""
from __future__ import annotations

import pytest
from rich.style import Style
from rich.text import Text

from argos.tui.widgets.prompt import (
    SlashMenu,
    _EYE,
    _INK_BRIGHT,
    _INK_DIM,
    _INK_FAINT,
    _RAISE_2,
)

# ── constants cross-check (pin exact hex so a theme drift fails loudly) ──────

def test_raise_2_hex_matches_theme() -> None:
    """_RAISE_2 must equal the $raise-2 token (#23263A) from theme.py."""
    assert _RAISE_2 == "#23263A", (
        f"_RAISE_2 drifted from $raise-2: got {_RAISE_2!r}, expected '#23263A'"
    )


def test_eye_hex_matches_theme() -> None:
    """_EYE must equal $eye (#D9A85C)."""
    assert _EYE == "#D9A85C"


def test_ink_bright_hex_matches_theme() -> None:
    """_INK_BRIGHT must equal $ink-bright (#ECEEF5)."""
    assert _INK_BRIGHT == "#ECEEF5"


def test_ink_dim_hex_matches_theme() -> None:
    """_INK_DIM must equal $ink-dim (#7E869C)."""
    assert _INK_DIM == "#7E869C"


def test_ink_faint_hex_matches_theme() -> None:
    """_INK_FAINT must equal $ink-faint (#6B7494)."""
    assert _INK_FAINT == "#6B7494"


# ── helpers ───────────────────────────────────────────────────────────────────

def _capture_render(menu: SlashMenu) -> Text:
    """Monkey-patch SlashMenu.update() to capture the Rich Text it receives,
    then call _render_items().  Returns the captured Text object."""
    captured: list[Text] = []

    def _fake_update(content: object) -> None:  # noqa: ANN001
        if isinstance(content, Text):
            captured.append(content)

    menu.update = _fake_update  # type: ignore[method-assign]
    menu._render_items()
    assert captured, "_render_items() must call self.update() with a Text"
    return captured[0]


def _spans_with_bgcolor(t: Text, bgcolor: str) -> list[tuple[str, str]]:
    """Return (span_text, style_str) for every span whose style has the given bgcolor."""
    result = []
    for span in t._spans:
        style = span.style
        if isinstance(style, Style):
            if style.bgcolor and style.bgcolor.name and style.bgcolor.name.lower() == bgcolor.lstrip("#").lower():
                result.append((t.plain[span.start:span.end], str(style)))
        elif isinstance(style, str) and bgcolor.lower() in style.lower():
            result.append((t.plain[span.start:span.end], style))
    return result


def _spans_containing(t: Text, substring: str) -> list[tuple[str, object]]:
    """Return (span_text, style) for every span whose text contains *substring*."""
    return [
        (t.plain[span.start:span.end], span.style)
        for span in t._spans
        if substring in t.plain[span.start:span.end]
    ]


def _plain_of_span(t: Text, start: int, end: int) -> str:
    return t.plain[start:end]


# ── SlashMenu fixture ─────────────────────────────────────────────────────────

@pytest.fixture()
def menu() -> SlashMenu:
    """SlashMenu without a mounted Textual app."""
    m = SlashMenu()
    # Provide a no-op display setter so show_matches() doesn't crash headless.
    type(m).display = property(lambda self: True, lambda self, v: None)  # type: ignore[assignment]
    return m


# ── [MEDIUM] 选中行整行 $raise-2 底色块 ──────────────────────────────────────

class TestSelectedRowRaise2Bgcolor:
    """MEDIUM: 视觉稿 line 293 — selected row wrapped in $raise-2 bg block.

    Every segment of the selected row (▸ prefix, /cmd name, description)
    must carry bgcolor=#23263A (=$raise-2).  Non-selected rows must NOT
    carry that bgcolor.
    """

    def _setup_two_items(self, menu: SlashMenu) -> Text:
        """Load two commands, first selected (cursor=0), render."""
        menu._matches = [("tools", "列出所有工具"), ("yolo", "自动批准模式")]
        menu._cursor = 0
        return _capture_render(menu)

    def test_selected_prefix_has_raise2_bgcolor(self, menu: SlashMenu) -> None:
        """▸ prefix on the selected row must have bgcolor $raise-2."""
        t = self._setup_two_items(menu)
        prefix_spans = _spans_containing(t, "▸")
        assert prefix_spans, "Selected row must have a ▸ prefix span"
        _, style = prefix_spans[0]
        assert isinstance(style, Style), "▸ span style must be a rich.style.Style"
        bg = style.bgcolor
        assert bg is not None, "▸ span must have a bgcolor"
        # Rich stores colors as Color objects; convert to hex string for assertion
        bg_hex = f"#{bg.triplet.red:02X}{bg.triplet.green:02X}{bg.triplet.blue:02X}".upper()
        assert bg_hex == _RAISE_2.upper(), (
            f"▸ prefix bgcolor must be $raise-2 ({_RAISE_2}), got {bg_hex!r}"
        )

    def test_selected_cmdname_has_raise2_bgcolor(self, menu: SlashMenu) -> None:
        """/tools command name on selected row must have bgcolor $raise-2."""
        t = self._setup_two_items(menu)
        cmd_spans = _spans_containing(t, "/tools")
        assert cmd_spans, "Selected row must contain a /tools span"
        _, style = cmd_spans[0]
        assert isinstance(style, Style)
        bg = style.bgcolor
        assert bg is not None, "/tools span must have a bgcolor"
        bg_hex = f"#{bg.triplet.red:02X}{bg.triplet.green:02X}{bg.triplet.blue:02X}".upper()
        assert bg_hex == _RAISE_2.upper(), (
            f"/tools bgcolor must be $raise-2 ({_RAISE_2}), got {bg_hex!r}"
        )

    def test_selected_description_has_raise2_bgcolor(self, menu: SlashMenu) -> None:
        """Description text on selected row must have bgcolor $raise-2."""
        t = self._setup_two_items(menu)
        desc_spans = _spans_containing(t, "列出所有工具")
        assert desc_spans, "Selected row must contain a description span"
        _, style = desc_spans[0]
        assert isinstance(style, Style)
        bg = style.bgcolor
        assert bg is not None, "description span must have a bgcolor"
        bg_hex = f"#{bg.triplet.red:02X}{bg.triplet.green:02X}{bg.triplet.blue:02X}".upper()
        assert bg_hex == _RAISE_2.upper(), (
            f"description bgcolor must be $raise-2 ({_RAISE_2}), got {bg_hex!r}"
        )

    def test_unselected_row_has_no_raise2_bgcolor(self, menu: SlashMenu) -> None:
        """Non-selected rows must NOT have $raise-2 bgcolor."""
        t = self._setup_two_items(menu)
        # /yolo is index 1, cursor is 0 → not selected
        yolo_spans = _spans_containing(t, "/yolo")
        assert yolo_spans, "Unselected /yolo row must still appear in output"
        for span_text, style in yolo_spans:
            if isinstance(style, Style) and style.bgcolor is not None:
                bg = style.bgcolor
                bg_hex = f"#{bg.triplet.red:02X}{bg.triplet.green:02X}{bg.triplet.blue:02X}".upper()
                assert bg_hex != _RAISE_2.upper(), (
                    f"Unselected /yolo span must NOT have $raise-2 bgcolor, got {bg_hex!r}"
                )

    def test_selected_prefix_has_eye_color(self, menu: SlashMenu) -> None:
        """▸ prefix foreground must be $eye (#D9A85C)."""
        t = self._setup_two_items(menu)
        prefix_spans = _spans_containing(t, "▸")
        assert prefix_spans
        _, style = prefix_spans[0]
        assert isinstance(style, Style)
        fg = style.color
        assert fg is not None, "▸ span must have a foreground color"
        fg_hex = f"#{fg.triplet.red:02X}{fg.triplet.green:02X}{fg.triplet.blue:02X}".upper()
        assert fg_hex == _EYE.upper(), (
            f"▸ prefix foreground must be $eye ({_EYE}), got {fg_hex!r}"
        )

    def test_selected_cmdname_has_ink_bright_color(self, menu: SlashMenu) -> None:
        """/cmd name foreground on selected row must be $ink-bright (#ECEEF5)."""
        t = self._setup_two_items(menu)
        cmd_spans = _spans_containing(t, "/tools")
        assert cmd_spans
        _, style = cmd_spans[0]
        assert isinstance(style, Style)
        fg = style.color
        assert fg is not None
        fg_hex = f"#{fg.triplet.red:02X}{fg.triplet.green:02X}{fg.triplet.blue:02X}".upper()
        assert fg_hex == _INK_BRIGHT.upper(), (
            f"/tools foreground must be $ink-bright ({_INK_BRIGHT}), got {fg_hex!r}"
        )

    def test_cursor_moves_raise2_to_new_selection(self, menu: SlashMenu) -> None:
        """After move(+1), second item becomes selected and gets $raise-2 bg."""
        menu._matches = [("tools", "工具"), ("yolo", "自动批准")]
        menu._cursor = 0
        # Patch update BEFORE move() so _render_items() inside move() is captured.
        captured: list[Text] = []
        menu.update = lambda c: captured.append(c) if isinstance(c, Text) else None  # type: ignore[method-assign]
        menu.move(1)  # cursor moves to index 1 (/yolo)
        assert captured, "move() must trigger _render_items() → update()"
        t = captured[-1]

        # /yolo is now selected — must have raise-2
        yolo_spans = _spans_containing(t, "/yolo")
        assert yolo_spans
        _, style = yolo_spans[0]
        assert isinstance(style, Style)
        bg = style.bgcolor
        assert bg is not None
        bg_hex = f"#{bg.triplet.red:02X}{bg.triplet.green:02X}{bg.triplet.blue:02X}".upper()
        assert bg_hex == _RAISE_2.upper(), (
            f"After move, /yolo bgcolor must be $raise-2 ({_RAISE_2}), got {bg_hex!r}"
        )

        # /tools is now unselected — must NOT have raise-2
        tools_spans = _spans_containing(t, "/tools")
        assert tools_spans
        for _, st in tools_spans:
            if isinstance(st, Style) and st.bgcolor is not None:
                bg2 = st.bgcolor
                bg2_hex = f"#{bg2.triplet.red:02X}{bg2.triplet.green:02X}{bg2.triplet.blue:02X}".upper()
                assert bg2_hex != _RAISE_2.upper(), (
                    f"After move, /tools must NOT have $raise-2 bgcolor, got {bg2_hex!r}"
                )


# ── [MEDIUM] hint line uses $ink-faint ───────────────────────────────────────

class TestHintLineColor:
    """↑↓ hint line at the bottom of SlashMenu must use $ink-faint (#6B7494)."""

    def test_hint_is_ink_faint(self, menu: SlashMenu) -> None:
        menu._matches = [("tools", "工具")]
        menu._cursor = 0
        t = _capture_render(menu)
        # The hint text contains "↑↓"
        hint_spans = _spans_containing(t, "↑↓")
        assert hint_spans, "Hint line '↑↓ 选择 · ↹ 补全 · ↵ 执行' must appear"
        _, style = hint_spans[0]
        style_str = str(style)
        assert _INK_FAINT.lower() in style_str.lower(), (
            f"Hint line must use $ink-faint ({_INK_FAINT}), got {style_str!r}"
        )


# ── plain-text content sanity ─────────────────────────────────────────────────

class TestPlainTextContent:
    """_render_items() plain text must be correct regardless of color."""

    def test_selected_row_has_arrow_prefix(self, menu: SlashMenu) -> None:
        menu._matches = [("tools", "列出工具")]
        menu._cursor = 0
        t = _capture_render(menu)
        assert "▸" in t.plain

    def test_unselected_row_has_no_arrow(self, menu: SlashMenu) -> None:
        menu._matches = [("tools", "工具"), ("yolo", "自动")]
        menu._cursor = 0
        t = _capture_render(menu)
        # Only one ▸ should appear (for selected item)
        assert t.plain.count("▸") == 1

    def test_all_commands_appear_in_output(self, menu: SlashMenu) -> None:
        menu._matches = [("tools", "工具"), ("yolo", "自动"), ("dream", "整合")]
        menu._cursor = 1
        t = _capture_render(menu)
        assert "/tools" in t.plain
        assert "/yolo" in t.plain
        assert "/dream" in t.plain

    def test_hint_line_appears(self, menu: SlashMenu) -> None:
        menu._matches = [("tools", "工具")]
        menu._cursor = 0
        t = _capture_render(menu)
        assert "↑↓" in t.plain
        assert "↹" in t.plain
        assert "↵" in t.plain


# ── show_matches API ──────────────────────────────────────────────────────────

class TestShowMatchesApi:
    """show_matches() must reset cursor on new match set."""

    def test_cursor_resets_on_new_matches(self, menu: SlashMenu) -> None:
        menu._matches = [("a", ""), ("b", "")]
        menu._cursor = 1
        # show_matches with a different list → cursor must reset to 0
        # We intercept update to avoid needing display setter
        menu.update = lambda _: None  # type: ignore[method-assign]
        menu.show_matches([("x", "desc1"), ("y", "desc2")])
        assert menu._cursor == 0

    def test_same_matches_keeps_cursor(self, menu: SlashMenu) -> None:
        menu._matches = [("a", ""), ("b", "")]
        menu._cursor = 1
        menu.update = lambda _: None  # type: ignore[method-assign]
        # Same list → cursor preserved
        menu.show_matches([("a", ""), ("b", "")])
        assert menu._cursor == 1

    def test_selected_returns_cursor_item(self, menu: SlashMenu) -> None:
        menu._matches = [("tools", ""), ("yolo", "")]
        menu._cursor = 1
        assert menu.selected() == "yolo"

    def test_selected_returns_none_on_empty(self, menu: SlashMenu) -> None:
        menu._matches = []
        assert menu.selected() is None
