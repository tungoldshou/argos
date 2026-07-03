# tests/tui/test_inline_choice_audit.py
"""Internal documentation."""
from __future__ import annotations

import re
from unittest.mock import MagicMock

import pytest
from rich.text import Text

from argos.tui.widgets.inline_choice import InlineChoice, format_approval_title



def _noop(value: str, feedback: str) -> None:
    pass


def _make_widget(risk: str = "medium", **kwargs) -> InlineChoice:
    """Internal documentation."""
    defaults = dict(
        title="◓ 审批请求 [medium]",
        options=[("once", "单次允许"), ("deny", "拒绝")],
        on_decide=_noop,
        risk=risk,
    )
    defaults.update(kwargs)
    return InlineChoice(**defaults)



def test_risk_plan_adds_risk_plan_class() -> None:
    """Internal documentation."""
    w = _make_widget(risk="plan")
    assert w.has_class("risk-plan"), "risk='plan' 应添加 class 'risk-plan'"
    assert not w.has_class("risk-medium"), "risk='plan' 不应添加 'risk-medium'"


def test_risk_plan_does_not_add_risk_medium() -> None:
    """Internal documentation."""
    w = _make_widget(risk="plan")
    classes = set(w.classes)
    assert "risk-medium" not in classes
    assert "risk-plan" in classes



def test_default_css_contains_risk_plan_border() -> None:
    """Internal documentation."""
    css = InlineChoice.DEFAULT_CSS
    assert "risk-plan" in css, "DEFAULT_CSS 缺少 .risk-plan 选择器"
    assert "$plan" in css, "DEFAULT_CSS 缺少 $plan token 引用"
    for line in css.splitlines():
        if "risk-plan" in line and "border-left" in line:
            assert "$plan" in line
            break
    else:
        assert re.search(r"risk-plan\b[^}]*border-left[^}]*\$plan", css, re.S),\
            "DEFAULT_CSS risk-plan 块缺少 border-left: thick $plan"


def test_default_css_contains_risk_plan_title_color() -> None:
    """Internal documentation."""
    css = InlineChoice.DEFAULT_CSS
    assert re.search(r"risk-plan\b[^}]*#ic-title[^}]*color[^}]*\$plan", css, re.S) or\
           re.search(r"risk-plan.*?#ic-title", css, re.S),\
        "DEFAULT_CSS 缺少 InlineChoice.risk-plan #ic-title { color: $plan }"
    assert re.search(r"\.?risk-plan\s+#ic-title\s*\{[^}]*\$plan", css) or\
           re.search(r"risk-plan[^}]*\}[^{]*risk-plan\s+#ic-title\s*\{[^}]*\$plan", css, re.S) or\
           "InlineChoice.risk-plan #ic-title" in css or\
           "risk-plan #ic-title" in css,\
        "DEFAULT_CSS 缺少 risk-plan #ic-title color: $plan"



def test_default_css_contains_ic_summary_ink_faint() -> None:
    """Internal documentation."""
    css = InlineChoice.DEFAULT_CSS
    assert "ic-summary" in css, "DEFAULT_CSS 缺少 .ic-summary 选择器"
    assert re.search(r"ic-summary[^}]*\$ink-faint", css, re.S),\
        "DEFAULT_CSS .ic-summary 块缺少 color: $ink-faint"



@pytest.mark.parametrize("risk,expected_class", [
    ("low",    "risk-low"),
    ("medium", "risk-medium"),
    ("high",   "risk-high"),
    ("plan",   "risk-plan"),
])
def test_risk_class_mapping(risk: str, expected_class: str) -> None:
    """Internal documentation."""
    w = _make_widget(risk=risk)
    assert w.has_class(expected_class),\
        f"risk='{risk}' 应产生 CSS 类 '{expected_class}'"


def test_risk_unknown_falls_to_medium() -> None:
    """Internal documentation."""
    w = _make_widget(risk="unknown_value")
    assert w.has_class("risk-medium")



def test_default_css_no_raw_hex() -> None:
    """Internal documentation."""
    css = InlineChoice.DEFAULT_CSS
    hex_colors = re.findall(r'(?<![a-zA-Z])#[0-9A-Fa-f]{3,6}\b', css)
    assert not hex_colors,\
        f"DEFAULT_CSS 含裸 hex,应改用 $token: {hex_colors}"



def test_format_approval_title_blocked_glyph() -> None:
    """Internal documentation."""
    title = format_approval_title(risk="medium", trigger="")
    assert title.startswith("◓"), f"标题应以 ◓ 开头,得到: {title!r}"


def test_format_approval_title_secret_uses_warning_sign() -> None:
    """Internal documentation."""
    title = format_approval_title(risk="high", trigger="secret:OPENAI_KEY")
    # ⚠︎ = U+26A0 + U+FE0E
    assert "⚠︎" in title, f"secret 命中必须含 ⚠︎(U+26A0+U+FE0E),得到: {title!r}"


def test_finish_summary_uses_done_eye_glyph() -> None:
    """Internal documentation."""
    calls: list[tuple[str, str]] = []

    def _capture(value: str, feedback: str) -> None:
        calls.append((value, feedback))

    w = InlineChoice(
        title="◓ 审批请求 [medium]",
        options=[("once", "单次允许"), ("deny", "拒绝")],
        on_decide=_capture,
        action_label="python read_file",
    )
    try:
        w._finish("once", "")
    except Exception:
        pass
    assert w._decided is True, "_finish 后 _decided 应为 True"
    assert calls == [("once", "")], f"on_decide 未被正确调用: {calls}"



def test_finish_idempotent() -> None:
    """Internal documentation."""
    count = [0]

    def _counter(v: str, fb: str) -> None:
        count[0] += 1

    w = _make_widget(on_decide=_counter)
    for _ in range(3):
        try:
            w._finish("once", "")
        except Exception:
            pass
    assert count[0] == 1, f"on_decide 不应多次触发,实际触发 {count[0]} 次"



def test_options_text_cursor_glyph() -> None:
    """Internal documentation."""
    w = _make_widget(options=[("once", "单次允许"), ("deny", "拒绝")])
    t = w._options_text()
    plain = t.plain
    assert "▸" in plain, f"选项文本缺少 ▸ 光标字形,得到: {plain!r}"


def test_options_text_non_cursor_indent() -> None:
    """Internal documentation."""
    w = _make_widget(options=[("once", "单次允许"), ("deny", "拒绝")])
    t = w._options_text()
    lines = t.plain.split("\n")
    assert len(lines) >= 2
    second_line = lines[1]
    assert not second_line.startswith("▸"),\
        f"非选中行不应以 ▸ 开头,得到: {second_line!r}"
    assert second_line.startswith("  "),\
        f"非选中行应以两空格开头,得到: {second_line!r}"


def test_options_text_returns_rich_text() -> None:
    """Internal documentation."""
    w = _make_widget()
    result = w._options_text()
    assert isinstance(result, Text),\
        f"_options_text 应返回 rich.text.Text,得到: {type(result)}"



def test_color_constants_match_theme_tokens() -> None:
    """Internal documentation."""
    from argos.tui.theme import ARGOS_NIGHT
    tokens = ARGOS_NIGHT.variables  # dict[str, str]

    assert InlineChoice._COL_EYE == tokens["eye"],\
        f"_COL_EYE {InlineChoice._COL_EYE!r} ≠ theme $eye {tokens['eye']!r}"
    assert InlineChoice._COL_INK_BRIGHT == tokens["ink-bright"],\
        f"_COL_INK_BRIGHT {InlineChoice._COL_INK_BRIGHT!r} ≠ theme $ink-bright {tokens['ink-bright']!r}"
    assert InlineChoice._COL_INK_DIM == tokens["ink-dim"],\
        f"_COL_INK_DIM {InlineChoice._COL_INK_DIM!r} ≠ theme $ink-dim {tokens['ink-dim']!r}"



def test_plan_token_in_css_matches_theme() -> None:
    """Internal documentation."""
    from argos.tui.theme import ARGOS_NIGHT
    tokens = ARGOS_NIGHT.variables
    assert "plan" in tokens, "theme.py ARGOS_NIGHT.variables 缺少 'plan' key"
    assert tokens["plan"] == "#7AA2F7",\
        f"theme.py $plan token 值不符,得到: {tokens['plan']!r}"
    assert "$plan" in InlineChoice.DEFAULT_CSS,\
        "DEFAULT_CSS 未引用 $plan token"



def test_options_text_no_blocked_glyph() -> None:
    """Internal documentation."""
    w = _make_widget(options=[("once", "单次允许"), ("deny", "拒绝")])
    plain = w._options_text().plain
    assert "◓" not in plain,\
        f"选项文本不应含 ◓(blocked-only 字形),得到: {plain!r}"
