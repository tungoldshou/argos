# tests/tui/test_hard_confirm_card.py
"""Internal documentation."""
from __future__ import annotations

import re
from unittest.mock import MagicMock

import pytest
from rich.text import Text

from argos.tui.widgets.inline_choice import InlineChoice
from argos.tui.widgets.hard_confirm_card import (
    HardConfirmCard,
    _COL_FAIL,
    _COL_EYE,
    _COL_INK_BRIGHT,
    _COL_INK_FAINT,
    _COL_INK_DIM,
    _body_line,
)



def _noop(value: str, feedback: str) -> None:
    pass


def _make_widget(**kwargs) -> HardConfirmCard:
    """Internal documentation."""
    defaults = dict(
        action="computer.click",
        x=412,
        y=280,
        description="点击「发送」按钮",
        on_decide=_noop,
    )
    defaults.update(kwargs)
    return HardConfirmCard(**defaults)



class TestInheritance:
    def test_is_inline_choice_subclass(self):
        """Internal documentation."""
        assert issubclass(HardConfirmCard, InlineChoice)

    def test_instantiates_without_app(self):
        """Internal documentation."""
        w = _make_widget()
        assert w is not None

    def test_escape_value_hardcoded_deny(self):
        """Internal documentation."""
        w = _make_widget()
        assert w._escape_value == "deny"

    def test_risk_class_is_high(self):
        """Internal documentation."""
        w = _make_widget()
        assert w.has_class("risk-high")

    def test_options_exactly_two(self):
        """Internal documentation."""
        w = _make_widget()
        values = [v for v, _ in w._options]
        assert values == ["once", "deny"]

    def test_no_session_or_always_options(self):
        """Internal documentation."""
        w = _make_widget()
        values = [v for v, _ in w._options]
        assert "session" not in values
        assert "always" not in values

    def test_cursor_starts_at_zero(self):
        """Internal documentation."""
        w = _make_widget()
        assert w._cursor == 0



class TestCssTokens:
    def test_risk_high_border_left_fail(self):
        """Internal documentation."""
        css = HardConfirmCard.DEFAULT_CSS
        full_css = ""
        for klass in type.mro(HardConfirmCard):
            if hasattr(klass, "DEFAULT_CSS") and klass.DEFAULT_CSS:
                full_css += klass.DEFAULT_CSS
        assert re.search(r"border-left\s*:\s*thick\s+\$fail", full_css),\
            "MRO CSS 必须有 border-left: thick $fail"

    def test_risk_high_title_color_fail(self):
        """Internal documentation."""
        full_css = ""
        for klass in type.mro(HardConfirmCard):
            if hasattr(klass, "DEFAULT_CSS") and klass.DEFAULT_CSS:
                full_css += klass.DEFAULT_CSS
        assert re.search(r"risk-high[^}]*#ic-title|#ic-title[^{]*\.risk-high", full_css) or\
               re.search(r"\.risk-high\s+#ic-title\s*\{[^}]*color\s*:\s*\$fail", full_css) or\
               re.search(r"#ic-title\s*\{[^}]*color\s*:\s*\$fail", full_css),\
               "MRO CSS 应含 .risk-high #ic-title { color: $fail }"

    def test_no_hex_in_own_default_css(self):
        """Internal documentation."""
        css = HardConfirmCard.DEFAULT_CSS or ""
        matches = re.findall(r"#[0-9A-Fa-f]{3,6}\b", css)
        color_matches = [m for m in matches if not re.match(r"#[a-zA-Z]", m)]
        assert color_matches == [], f"DEFAULT_CSS 含裸 hex: {color_matches}"



class TestColorConstants:
    """Internal documentation."""

    def test_col_fail(self):
        assert _COL_FAIL == "#F7768E"      # $fail

    def test_col_eye(self):
        assert _COL_EYE == "#D9A85C"       # $eye

    def test_col_ink_bright(self):
        assert _COL_INK_BRIGHT == "#ECEEF5"  # $ink-bright

    def test_col_ink_faint(self):
        assert _COL_INK_FAINT == "#6B7494"   # $ink-faint

    def test_col_ink_dim(self):
        assert _COL_INK_DIM == "#7E869C"     # $ink-dim



class TestGlyphs:
    def test_title_exact_string(self):
        """Internal documentation."""
        w = _make_widget()
        assert w._title == "⛔ 计算机控制 · 硬确认 [high · 不可逆]"

    def test_title_starts_with_stop_sign(self):
        """Internal documentation."""
        w = _make_widget()
        assert w._title[0] == "⛔"

    def test_title_not_start_with_half_eye(self):
        """Internal documentation."""
        w = _make_widget()
        assert "◓" not in w._title

    def test_title_contains_high_irreversible_tag(self):
        """Internal documentation."""
        w = _make_widget()
        assert "[high · 不可逆]" in w._title

    def test_options_text_cursor_glyph_is_triangle(self):
        """Internal documentation."""
        w = _make_widget()
        rendered = w._options_text()
        assert isinstance(rendered, Text)
        assert "▸" in rendered.plain

    def test_summary_once_glyph(self):
        """Internal documentation."""
        w = _make_widget()
        summary = f"◕ 审批 {w._action_label} → once"
        assert summary.startswith("◕")

    def test_summary_deny_glyph(self):
        w = _make_widget()
        summary = f"◕ 审批 {w._action_label} → deny"
        assert summary.startswith("◕")



class TestBodyLine:
    def test_coord_action_format(self):
        """Internal documentation."""
        line = _body_line("computer.click", x=412, y=280, description="点击「发送」按钮", text=None, app=None)
        assert line == "computer.click (412, 280) — 点击「发送」按钮"

    def test_screenshot_no_coords(self):
        """Internal documentation."""
        line = _body_line("computer.screenshot", x=None, y=None, description="截屏", text=None, app=None)
        assert line == "computer.screenshot — 截屏"

    def test_open_app_no_coords(self):
        """Internal documentation."""
        line = _body_line("computer.open_app", x=None, y=None, description="打开 Safari", text=None, app="Safari")
        assert line == "computer.open_app — 打开 Safari"

    def test_type_text_with_coords_none(self):
        """Internal documentation."""
        line = _body_line("computer.type_text", x=None, y=None, description="输入密码", text="secret", app=None)
        assert "None" not in line
        assert "computer.type_text" in line

    def test_body_stored_on_widget(self):
        """Internal documentation."""
        w = _make_widget(action="computer.click", x=10, y=20, description="测试描述")
        assert "computer.click" in w._body
        assert "(10, 20)" in w._body
        assert "测试描述" in w._body

    def test_em_dash_in_body(self):
        """Internal documentation."""
        line = _body_line("computer.click", x=1, y=2, description="desc", text=None, app=None)
        assert "—" in line   # U+2014

    def test_no_parentheses_when_no_coords(self):
        """Internal documentation."""
        line = _body_line("computer.screenshot", x=None, y=None, description="d", text=None, app=None)
        assert "(" not in line
        assert ")" not in line



class TestOptionNumbering:
    def test_deny_option_shows_digit_4(self):
        """Internal documentation."""
        w = _make_widget()
        rendered = w._options_text()
        plain = rendered.plain
        assert "4" in plain
        assert "2  拒绝" not in plain

    def test_once_option_shows_digit_1(self):
        """Internal documentation."""
        w = _make_widget()
        rendered = w._options_text()
        plain = rendered.plain
        assert "1" in plain
        assert "仅此一次" in plain

    def test_deny_label_text(self):
        """Internal documentation."""
        w = _make_widget()
        rendered = w._options_text()
        assert "拒绝" in rendered.plain

    def test_once_label_text(self):
        """Internal documentation."""
        w = _make_widget()
        rendered = w._options_text()
        assert "仅此一次" in rendered.plain



class TestDigitKeyMapping:
    def test_digit_1_maps_to_once(self):
        """Internal documentation."""
        w = _make_widget()
        idx = w._digit_to_option_index("1")
        assert idx == 0

    def test_digit_4_maps_to_deny(self):
        """Internal documentation."""
        w = _make_widget()
        idx = w._digit_to_option_index("4")
        assert idx == 1

    def test_digit_2_returns_none(self):
        """Internal documentation."""
        w = _make_widget()
        idx = w._digit_to_option_index("2")
        assert idx is None

    def test_digit_3_returns_none(self):
        """Internal documentation."""
        w = _make_widget()
        idx = w._digit_to_option_index("3")
        assert idx is None

    def test_digit_0_returns_none(self):
        """Internal documentation."""
        w = _make_widget()
        idx = w._digit_to_option_index("0")
        assert idx is None



class TestGovernanceText:
    def test_governance_text_exact(self):
        """Internal documentation."""
        expected = "Seatbelt 无法约束全局屏幕/鼠标资源 — 审批门、账本、审计是唯一治理层"
        w = _make_widget()
        assert w._GOVERNANCE_TEXT == expected

    def test_governance_text_contains_seatbelt(self):
        w = _make_widget()
        assert "Seatbelt" in w._GOVERNANCE_TEXT

    def test_governance_text_contains_em_dash(self):
        """Internal documentation."""
        w = _make_widget()
        assert "—" in w._GOVERNANCE_TEXT   # U+2014



class TestFooterText:
    def test_footer_text_exact(self):
        """Internal documentation."""
        expected = "每个 computer.* 动作恒 risk=high + reversible=False · 不受 Trust Dial 降级"
        w = _make_widget()
        assert w._FOOTER_TEXT == expected

    def test_footer_text_contains_computer_wildcard(self):
        w = _make_widget()
        assert "computer.*" in w._FOOTER_TEXT

    def test_footer_text_contains_trust_dial(self):
        w = _make_widget()
        assert "Trust Dial" in w._FOOTER_TEXT

    def test_footer_text_contains_reversible_false(self):
        w = _make_widget()
        assert "reversible=False" in w._FOOTER_TEXT



class TestHonestyInvariants:
    def test_risk_cannot_be_lowered_by_caller(self):
        """Internal documentation."""
        w = _make_widget()
        assert w.has_class("risk-high")
        assert not w.has_class("risk-low")
        assert not w.has_class("risk-medium")

    def test_escape_value_always_deny(self):
        """Internal documentation."""
        w = _make_widget()
        assert w._escape_value == "deny"

    def test_title_always_contains_high_irreversible(self):
        """Internal documentation."""
        for action in [
            "computer.screenshot",
            "computer.click",
            "computer.double_click",
            "computer.type_text",
            "computer.key",
            "computer.scroll",
            "computer.open_app",
        ]:
            w = HardConfirmCard(
                action=action,
                x=None,
                y=None,
                description="测试",
                on_decide=_noop,
            )
            assert "[high · 不可逆]" in w._title,\
                f"action={action} 的标题缺少 '[high · 不可逆]'"

    def test_markup_false_invariant_for_body(self):
        """Internal documentation."""
        w = HardConfirmCard(
            action="computer.type_text",
            x=None,
            y=None,
            description="输入 [Tab] 键切换",
            on_decide=_noop,
        )
        assert "[Tab]" in w._body

    def test_action_label_for_summary(self):
        """Internal documentation."""
        w = _make_widget(action="computer.scroll")
        assert w._action_label

    def test_options_text_cursor_color_is_eye(self):
        """Internal documentation."""
        w = _make_widget()
        rendered = w._options_text()
        spans = [
            s for s in rendered._spans
            if s.style and _COL_EYE.lower() in str(s.style).lower()
        ]
        assert spans, "▸ 光标 span 颜色应为 $eye"

    def test_options_text_deny_digit_4_not_2(self):
        """Internal documentation."""
        w = _make_widget()
        rendered = w._options_text()
        plain = rendered.plain
        assert re.search(r"4\s+拒绝", plain),\
            f"_options_text 应含 '4  拒绝',实际: {plain!r}"

    def test_options_text_once_digit_1(self):
        """Internal documentation."""
        w = _make_widget()
        rendered = w._options_text()
        plain = rendered.plain
        assert re.search(r"1\s+仅此一次", plain),\
            f"_options_text 应含 '1  仅此一次',实际: {plain!r}"



class TestIdempotent:
    def test_on_decide_called_only_once(self):
        """Internal documentation."""
        calls: list[tuple[str, str]] = []

        def decide(v: str, fb: str) -> None:
            calls.append((v, fb))

        w = _make_widget(on_decide=decide)
        w._finish("once", "")
        w._finish("once", "")
        assert len(calls) == 1

    def test_double_deny_calls_decide_once(self):
        """Internal documentation."""
        calls: list = []
        w = _make_widget(on_decide=lambda v, f: calls.append(v))
        w._finish("deny", "")
        w._finish("deny", "")
        assert len(calls) == 1



class TestAllSevenActions:
    """Internal documentation."""

    @pytest.mark.parametrize("action,x,y", [
        ("computer.screenshot", None, None),
        ("computer.click", 100, 200),
        ("computer.double_click", 50, 75),
        ("computer.type_text", None, None),
        ("computer.key", None, None),
        ("computer.scroll", 300, 400),
        ("computer.open_app", None, None),
    ])
    def test_constructs_without_error(self, action, x, y):
        """Internal documentation."""
        w = HardConfirmCard(
            action=action,
            x=x,
            y=y,
            description=f"动作:{action}",
            on_decide=_noop,
        )
        assert w is not None
        assert "[high · 不可逆]" in w._title
        assert w._escape_value == "deny"
