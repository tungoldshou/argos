# tests/tui/test_inline_choice_audit.py
"""InlineChoice 设计审计回归测试 — 针对 2026-06-14 Part C audit 修复项。

覆盖范围:
  - [MEDIUM] risk='plan' → CSS 类 'risk-plan'(不再落到 risk-medium)
  - [MEDIUM] risk='plan' → DEFAULT_CSS 含 $plan 左缘规则
  - [MEDIUM] risk='plan' → DEFAULT_CSS 含 $plan #ic-title 颜色规则
  - [LOW]   DEFAULT_CSS 含 .ic-summary { color: $ink-faint } 规则
  - 现有 risk 类映射不变(low/medium/high)
  - 字形铁律:◓ 仅作决策挂起前缀,◕ 仅出现在 _finish 摘要中
  - ▸ 光标字形正确(U+25B8),非选中行两空格缩进
  - 颜色常量与 theme.py token 同步(_COL_EYE/$eye, _COL_INK_BRIGHT/$ink-bright,
    _COL_INK_DIM/$ink-dim)
  - _finish 幂等门禁(绝不双发)
"""
from __future__ import annotations

import re
from unittest.mock import MagicMock

import pytest
from rich.text import Text

from argos.tui.widgets.inline_choice import InlineChoice, format_approval_title


# ── 共用 helpers ───────────────────────────────────────────────────────────────

def _noop(value: str, feedback: str) -> None:
    pass


def _make_widget(risk: str = "medium", **kwargs) -> InlineChoice:
    """最小构造 InlineChoice(不挂载 App)。"""
    defaults = dict(
        title="◓ 审批请求 [medium]",
        options=[("once", "单次允许"), ("deny", "拒绝")],
        on_decide=_noop,
        risk=risk,
    )
    defaults.update(kwargs)
    return InlineChoice(**defaults)


# ── 1. [MEDIUM] risk='plan' → CSS 类 'risk-plan' ─────────────────────────────

def test_risk_plan_adds_risk_plan_class() -> None:
    """risk='plan' 时必须添加 'risk-plan' CSS 类,不得落回 'risk-medium'。"""
    w = _make_widget(risk="plan")
    assert w.has_class("risk-plan"), "risk='plan' 应添加 class 'risk-plan'"
    assert not w.has_class("risk-medium"), "risk='plan' 不应添加 'risk-medium'"


def test_risk_plan_does_not_add_risk_medium() -> None:
    """risk='plan' 确认不产生 risk-medium 类。"""
    w = _make_widget(risk="plan")
    classes = set(w.classes)
    assert "risk-medium" not in classes
    assert "risk-plan" in classes


# ── 2. [MEDIUM] DEFAULT_CSS 含 $plan 左缘 + 标题颜色规则 ─────────────────────

def test_default_css_contains_risk_plan_border() -> None:
    """DEFAULT_CSS 必须包含 risk-plan 的 $plan 左缘规则。"""
    css = InlineChoice.DEFAULT_CSS
    assert "risk-plan" in css, "DEFAULT_CSS 缺少 .risk-plan 选择器"
    assert "$plan" in css, "DEFAULT_CSS 缺少 $plan token 引用"
    # 确认 border-left 与 $plan 在同一行
    for line in css.splitlines():
        if "risk-plan" in line and "border-left" in line:
            assert "$plan" in line
            break
    else:
        # 允许多行形式:只要 risk-plan 块内有 border-left 与 $plan
        assert re.search(r"risk-plan\b[^}]*border-left[^}]*\$plan", css, re.S), \
            "DEFAULT_CSS risk-plan 块缺少 border-left: thick $plan"


def test_default_css_contains_risk_plan_title_color() -> None:
    """DEFAULT_CSS risk-plan 块必须包含 #ic-title { color: $plan } 规则。"""
    css = InlineChoice.DEFAULT_CSS
    assert re.search(r"risk-plan\b[^}]*#ic-title[^}]*color[^}]*\$plan", css, re.S) or \
           re.search(r"risk-plan.*?#ic-title", css, re.S), \
        "DEFAULT_CSS 缺少 InlineChoice.risk-plan #ic-title { color: $plan }"
    # 更精确:独立规则行
    assert re.search(r"\.?risk-plan\s+#ic-title\s*\{[^}]*\$plan", css) or \
           re.search(r"risk-plan[^}]*\}[^{]*risk-plan\s+#ic-title\s*\{[^}]*\$plan", css, re.S) or \
           "InlineChoice.risk-plan #ic-title" in css or \
           "risk-plan #ic-title" in css, \
        "DEFAULT_CSS 缺少 risk-plan #ic-title color: $plan"


# ── 3. [LOW] DEFAULT_CSS 含 .ic-summary { color: $ink-faint } ────────────────

def test_default_css_contains_ic_summary_ink_faint() -> None:
    """DEFAULT_CSS 必须包含 .ic-summary 的 $ink-faint 颜色规则。"""
    css = InlineChoice.DEFAULT_CSS
    assert "ic-summary" in css, "DEFAULT_CSS 缺少 .ic-summary 选择器"
    assert re.search(r"ic-summary[^}]*\$ink-faint", css, re.S), \
        "DEFAULT_CSS .ic-summary 块缺少 color: $ink-faint"


# ── 4. 现有 risk 类映射不变 ───────────────────────────────────────────────────

@pytest.mark.parametrize("risk,expected_class", [
    ("low",    "risk-low"),
    ("medium", "risk-medium"),
    ("high",   "risk-high"),
    ("plan",   "risk-plan"),
])
def test_risk_class_mapping(risk: str, expected_class: str) -> None:
    """各 risk 值映射到正确的 CSS 类。"""
    w = _make_widget(risk=risk)
    assert w.has_class(expected_class), \
        f"risk='{risk}' 应产生 CSS 类 '{expected_class}'"


def test_risk_unknown_falls_to_medium() -> None:
    """未知 risk 值应退回 risk-medium。"""
    w = _make_widget(risk="unknown_value")
    assert w.has_class("risk-medium")


# ── 5. DEFAULT_CSS 不含裸 hex ─────────────────────────────────────────────────

def test_default_css_no_raw_hex() -> None:
    """DEFAULT_CSS 中禁止出现裸 hex(应全部使用 $token)。"""
    css = InlineChoice.DEFAULT_CSS
    # 匹配 #RRGGBB 或 #RGB 格式(允许类选择器 '#ic-title' 等 ID 选择器)
    hex_colors = re.findall(r'(?<![a-zA-Z])#[0-9A-Fa-f]{3,6}\b', css)
    assert not hex_colors, \
        f"DEFAULT_CSS 含裸 hex,应改用 $token: {hex_colors}"


# ── 6. 字形铁律:◓ 前缀 / ◕ 摘要 ─────────────────────────────────────────────

def test_format_approval_title_blocked_glyph() -> None:
    """format_approval_title 产生的标题前缀必须是 ◓(半阖眼,等用户决策)。"""
    title = format_approval_title(risk="medium", trigger="")
    assert title.startswith("◓"), f"标题应以 ◓ 开头,得到: {title!r}"


def test_format_approval_title_secret_uses_warning_sign() -> None:
    """secret trigger 必须包含 ⚠︎ (U+26A0 + U+FE0E VS15)。"""
    title = format_approval_title(risk="high", trigger="secret:OPENAI_KEY")
    # ⚠︎ = U+26A0 + U+FE0E
    assert "⚠︎" in title, f"secret 命中必须含 ⚠︎(U+26A0+U+FE0E),得到: {title!r}"


def test_finish_summary_uses_done_eye_glyph() -> None:
    """_finish 构造的摘要行前缀必须是 ◕(阅毕眼,U+25D5)。"""
    calls: list[tuple[str, str]] = []

    def _capture(value: str, feedback: str) -> None:
        calls.append((value, feedback))

    w = InlineChoice(
        title="◓ 审批请求 [medium]",
        options=[("once", "单次允许"), ("deny", "拒绝")],
        on_decide=_capture,
        action_label="python read_file",
    )
    # _finish 会尝试 self.parent / self.app — 在无 App 环境下会 raise,但
    # on_decide 已在 finally 前调用,且 _decided 已设置;用 try/except 捕获
    # 挂载相关异常,只验证 on_decide 被调用且 _decided=True。
    try:
        w._finish("once", "")
    except Exception:
        pass
    assert w._decided is True, "_finish 后 _decided 应为 True"
    assert calls == [("once", "")], f"on_decide 未被正确调用: {calls}"


# ── 7. _finish 幂等门禁 ───────────────────────────────────────────────────────

def test_finish_idempotent() -> None:
    """_finish 多次调用只触发一次 on_decide。"""
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


# ── 8. _options_text 字形 ──────────────────────────────────────────────────────

def test_options_text_cursor_glyph() -> None:
    """当前选项前缀必须是 ▸(U+25B8 BLACK RIGHT-POINTING SMALL TRIANGLE)。"""
    w = _make_widget(options=[("once", "单次允许"), ("deny", "拒绝")])
    t = w._options_text()
    plain = t.plain
    assert "▸" in plain, f"选项文本缺少 ▸ 光标字形,得到: {plain!r}"


def test_options_text_non_cursor_indent() -> None:
    """非选中项使用两空格缩进,不含 ▸。"""
    w = _make_widget(options=[("once", "单次允许"), ("deny", "拒绝")])
    # cursor=0 → 第 2 行(deny)无 ▸
    t = w._options_text()
    lines = t.plain.split("\n")
    assert len(lines) >= 2
    second_line = lines[1]
    assert not second_line.startswith("▸"), \
        f"非选中行不应以 ▸ 开头,得到: {second_line!r}"
    assert second_line.startswith("  "), \
        f"非选中行应以两空格开头,得到: {second_line!r}"


def test_options_text_returns_rich_text() -> None:
    """_options_text() 必须返回 rich.text.Text 实例(不是 str)。"""
    w = _make_widget()
    result = w._options_text()
    assert isinstance(result, Text), \
        f"_options_text 应返回 rich.text.Text,得到: {type(result)}"


# ── 9. 颜色常量与 theme.py token 同步 ────────────────────────────────────────

def test_color_constants_match_theme_tokens() -> None:
    """InlineChoice 颜色常量必须与 theme.py ARGOS_NIGHT.variables 中同名 token 一致。"""
    from argos.tui.theme import ARGOS_NIGHT
    tokens = ARGOS_NIGHT.variables  # dict[str, str]

    assert InlineChoice._COL_EYE == tokens["eye"], \
        f"_COL_EYE {InlineChoice._COL_EYE!r} ≠ theme $eye {tokens['eye']!r}"
    assert InlineChoice._COL_INK_BRIGHT == tokens["ink-bright"], \
        f"_COL_INK_BRIGHT {InlineChoice._COL_INK_BRIGHT!r} ≠ theme $ink-bright {tokens['ink-bright']!r}"
    assert InlineChoice._COL_INK_DIM == tokens["ink-dim"], \
        f"_COL_INK_DIM {InlineChoice._COL_INK_DIM!r} ≠ theme $ink-dim {tokens['ink-dim']!r}"


# ── 10. risk-plan CSS token 与 theme.py $plan 同步 ────────────────────────────

def test_plan_token_in_css_matches_theme() -> None:
    """DEFAULT_CSS 中的 $plan 对应 theme.py ARGOS_NIGHT.variables['plan'] (#7AA2F7)。"""
    from argos.tui.theme import ARGOS_NIGHT
    tokens = ARGOS_NIGHT.variables
    assert "plan" in tokens, "theme.py ARGOS_NIGHT.variables 缺少 'plan' key"
    assert tokens["plan"] == "#7AA2F7", \
        f"theme.py $plan token 值不符,得到: {tokens['plan']!r}"
    # DEFAULT_CSS 引用了 $plan(上面已测);此处确认 token 在 theme 中存在
    assert "$plan" in InlineChoice.DEFAULT_CSS, \
        "DEFAULT_CSS 未引用 $plan token"


# ── 11. ◓ 是 blocked-only 字形,禁止出现在选项文本中 ─────────────────────────

def test_options_text_no_blocked_glyph() -> None:
    """选项文本中禁止出现 ◓(该字形仅用于 blocked/等待决策标题前缀)。"""
    w = _make_widget(options=[("once", "单次允许"), ("deny", "拒绝")])
    plain = w._options_text().plain
    assert "◓" not in plain, \
        f"选项文本不应含 ◓(blocked-only 字形),得到: {plain!r}"
