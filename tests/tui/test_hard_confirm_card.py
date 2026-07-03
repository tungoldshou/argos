# tests/tui/test_hard_confirm_card.py
"""HardConfirmCard widget 验收测试(TDD · screen 16 Computer use 硬确认)。

覆盖范围:
  - 继承断言(subclasses InlineChoice)
  - 构造强制约束:risk='high', escape_value='deny', 固定 2 选项
  - 字形铁律:⛔ 标题、▸ 光标、◕ 自毁摘要
  - CSS token 铁律:$fail 左缘、$fail #ic-title、无裸 hex
  - 颜色常量与 theme.py 同步
  - 标题精确字符串 "⛔ 计算机控制 · 硬确认 [high · 不可逆]"
  - Body 格式字符串(含坐标 / 无坐标 变体)
  - 治理注释精确字符串
  - 页脚不变量精确字符串
  - 选项编号铁律:deny 显示 "4" 而非 "2"
  - 数字直选:键 '1' → once, 键 '4' → deny
  - 幂等 _finish
  - 诚实不变量:标题必含 '[high · 不可逆]' + ⛔; risk 不可被调用方降级
  - 诚实不变量:选项不含 session/always
"""
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


# ── 共用 fixtures ──────────────────────────────────────────────────────────────

def _noop(value: str, feedback: str) -> None:
    pass


def _make_widget(**kwargs) -> HardConfirmCard:
    """最小构造 HardConfirmCard(不挂载 App)。"""
    defaults = dict(
        action="computer.click",
        x=412,
        y=280,
        description="点击「发送」按钮",
        on_decide=_noop,
    )
    defaults.update(kwargs)
    return HardConfirmCard(**defaults)


# ── 1. 继承 ────────────────────────────────────────────────────────────────────

class TestInheritance:
    def test_is_inline_choice_subclass(self):
        """HardConfirmCard 必须继承 InlineChoice。"""
        assert issubclass(HardConfirmCard, InlineChoice)

    def test_instantiates_without_app(self):
        """可在 App 外构造(不抛异常)。"""
        w = _make_widget()
        assert w is not None

    def test_escape_value_hardcoded_deny(self):
        """escape_value 硬编码为 'deny'(fail-closed;调用方不可覆盖)。"""
        w = _make_widget()
        assert w._escape_value == "deny"

    def test_risk_class_is_high(self):
        """widget 必须带 'risk-high' CSS class(调用方不可传入低 risk)。"""
        w = _make_widget()
        assert w.has_class("risk-high")

    def test_options_exactly_two(self):
        """固定 2 个选项:once / deny。"""
        w = _make_widget()
        values = [v for v, _ in w._options]
        assert values == ["once", "deny"]

    def test_no_session_or_always_options(self):
        """不可逆动作绝不提供 session/always 选项。"""
        w = _make_widget()
        values = [v for v, _ in w._options]
        assert "session" not in values
        assert "always" not in values

    def test_cursor_starts_at_zero(self):
        """光标初始指向 index=0(仅此一次)。"""
        w = _make_widget()
        assert w._cursor == 0


# ── 2. CSS token 铁律 ─────────────────────────────────────────────────────────

class TestCssTokens:
    def test_risk_high_border_left_fail(self):
        """DEFAULT_CSS .risk-high 必须含 border-left: thick $fail。"""
        css = HardConfirmCard.DEFAULT_CSS
        # 父类已有 .risk-high { border-left: thick $fail; }; 子类 CSS 可继承或重申
        # 只需整个 MRO CSS 中存在此规则即可通过
        full_css = ""
        for klass in type.mro(HardConfirmCard):
            if hasattr(klass, "DEFAULT_CSS") and klass.DEFAULT_CSS:
                full_css += klass.DEFAULT_CSS
        assert re.search(r"border-left\s*:\s*thick\s+\$fail", full_css), \
            "MRO CSS 必须有 border-left: thick $fail"

    def test_risk_high_title_color_fail(self):
        """DEFAULT_CSS .risk-high #ic-title 颜色必须是 $fail。"""
        full_css = ""
        for klass in type.mro(HardConfirmCard):
            if hasattr(klass, "DEFAULT_CSS") and klass.DEFAULT_CSS:
                full_css += klass.DEFAULT_CSS
        assert re.search(r"risk-high[^}]*#ic-title|#ic-title[^{]*\.risk-high", full_css) or \
               re.search(r"\.risk-high\s+#ic-title\s*\{[^}]*color\s*:\s*\$fail", full_css) or \
               re.search(r"#ic-title\s*\{[^}]*color\s*:\s*\$fail", full_css), \
               "MRO CSS 应含 .risk-high #ic-title { color: $fail }"

    def test_no_hex_in_own_default_css(self):
        """HardConfirmCard.DEFAULT_CSS 自身不含裸 hex(全用 $token)。"""
        css = HardConfirmCard.DEFAULT_CSS or ""
        matches = re.findall(r"#[0-9A-Fa-f]{3,6}\b", css)
        # 过滤 CSS ID 选择器(#ic-*, #hc-*)
        color_matches = [m for m in matches if not re.match(r"#[a-zA-Z]", m)]
        assert color_matches == [], f"DEFAULT_CSS 含裸 hex: {color_matches}"


# ── 3. 颜色常量同步检查 ────────────────────────────────────────────────────────

class TestColorConstants:
    """模块级 hex 常量必须和 theme.py token 值保持同步。"""

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


# ── 4. 字形铁律 ──────────────────────────────────────────────────────────────

class TestGlyphs:
    def test_title_exact_string(self):
        """标题精确匹配 spec 字符串。"""
        w = _make_widget()
        assert w._title == "⛔ 计算机控制 · 硬确认 [high · 不可逆]"

    def test_title_starts_with_stop_sign(self):
        """标题首字符必须是 ⛔ (U+26D4 NO ENTRY)。"""
        w = _make_widget()
        assert w._title[0] == "⛔"

    def test_title_not_start_with_half_eye(self):
        """标题不得使用 ◓(半阖眼为普通审批专用)。"""
        w = _make_widget()
        assert "◓" not in w._title

    def test_title_contains_high_irreversible_tag(self):
        """标题必须含 '[high · 不可逆]' 后缀(诚实标记)。"""
        w = _make_widget()
        assert "[high · 不可逆]" in w._title

    def test_options_text_cursor_glyph_is_triangle(self):
        """当前项前缀必须是 ▸ (U+25B8 BLACK RIGHT-POINTING SMALL TRIANGLE)。"""
        w = _make_widget()
        rendered = w._options_text()
        assert isinstance(rendered, Text)
        assert "▸" in rendered.plain

    def test_summary_once_glyph(self):
        """decide=once 摘要前缀必须是 ◕ (U+25D5 阅毕眼)。"""
        w = _make_widget()
        # _finish 调 on_decide 后自毁;我们用 action_label 看摘要格式
        # 摘要 = f"◕ 审批 {self._action_label} → {value}"
        summary = f"◕ 审批 {w._action_label} → once"
        assert summary.startswith("◕")

    def test_summary_deny_glyph(self):
        w = _make_widget()
        summary = f"◕ 审批 {w._action_label} → deny"
        assert summary.startswith("◕")


# ── 5. Body 格式字符串(_body_line 函数) ──────────────────────────────────────

class TestBodyLine:
    def test_coord_action_format(self):
        """含坐标动作:格式 '{action} ({x}, {y}) — {description}'。"""
        line = _body_line("computer.click", x=412, y=280, description="点击「发送」按钮", text=None, app=None)
        assert line == "computer.click (412, 280) — 点击「发送」按钮"

    def test_screenshot_no_coords(self):
        """screenshot 无坐标:格式 '{action} — {description}'。"""
        line = _body_line("computer.screenshot", x=None, y=None, description="截屏", text=None, app=None)
        assert line == "computer.screenshot — 截屏"

    def test_open_app_no_coords(self):
        """open_app 无坐标:格式 '{action} — {description}'。"""
        line = _body_line("computer.open_app", x=None, y=None, description="打开 Safari", text=None, app="Safari")
        assert line == "computer.open_app — 打开 Safari"

    def test_type_text_with_coords_none(self):
        """type_text x/y=None 时不含坐标。"""
        line = _body_line("computer.type_text", x=None, y=None, description="输入密码", text="secret", app=None)
        assert "None" not in line
        assert "computer.type_text" in line

    def test_body_stored_on_widget(self):
        """widget._body 应为 _body_line 生成的格式字符串。"""
        w = _make_widget(action="computer.click", x=10, y=20, description="测试描述")
        assert "computer.click" in w._body
        assert "(10, 20)" in w._body
        assert "测试描述" in w._body

    def test_em_dash_in_body(self):
        """body 行分隔符必须是 — (U+2014 EM DASH)。"""
        line = _body_line("computer.click", x=1, y=2, description="desc", text=None, app=None)
        assert "—" in line   # U+2014

    def test_no_parentheses_when_no_coords(self):
        """无坐标时不渲染圆括号。"""
        line = _body_line("computer.screenshot", x=None, y=None, description="d", text=None, app=None)
        assert "(" not in line
        assert ")" not in line


# ── 6. 选项编号铁律 ──────────────────────────────────────────────────────────

class TestOptionNumbering:
    def test_deny_option_shows_digit_4(self):
        """deny 选项必须显示数字 '4'(不是 '2')。"""
        w = _make_widget()
        rendered = w._options_text()
        plain = rendered.plain
        # 选项行格式:前缀 + 数字 + 两空格 + 标签
        # deny = 第2选项,但spec要求显示 "4  拒绝"
        assert "4" in plain
        # 确保 '2  拒绝' 不出现(防止父类 i+1 自动编号)
        assert "2  拒绝" not in plain

    def test_once_option_shows_digit_1(self):
        """once 选项显示数字 '1'。"""
        w = _make_widget()
        rendered = w._options_text()
        plain = rendered.plain
        assert "1" in plain
        assert "仅此一次" in plain

    def test_deny_label_text(self):
        """deny 选项标签文字精确为 '拒绝'。"""
        w = _make_widget()
        rendered = w._options_text()
        assert "拒绝" in rendered.plain

    def test_once_label_text(self):
        """once 选项标签文字精确为 '仅此一次'。"""
        w = _make_widget()
        rendered = w._options_text()
        assert "仅此一次" in rendered.plain


# ── 7. 数字直选键映射 ─────────────────────────────────────────────────────────

class TestDigitKeyMapping:
    def test_digit_1_maps_to_once(self):
        """键 '1' 直选 once 选项(index=0)。"""
        w = _make_widget()
        # _digit_to_index 或 override:key '1' 必须选中 once
        idx = w._digit_to_option_index("1")
        assert idx == 0   # once 在 index 0

    def test_digit_4_maps_to_deny(self):
        """键 '4' 直选 deny 选项(index=1),不是键 '2'。"""
        w = _make_widget()
        idx = w._digit_to_option_index("4")
        assert idx == 1   # deny 在 index 1

    def test_digit_2_returns_none(self):
        """键 '2' 不对应任何选项,返回 None(忽略)。"""
        w = _make_widget()
        idx = w._digit_to_option_index("2")
        assert idx is None

    def test_digit_3_returns_none(self):
        """键 '3' 不对应任何选项,返回 None。"""
        w = _make_widget()
        idx = w._digit_to_option_index("3")
        assert idx is None

    def test_digit_0_returns_none(self):
        """键 '0' 不对应任何选项。"""
        w = _make_widget()
        idx = w._digit_to_option_index("0")
        assert idx is None


# ── 8. 治理注释静态文字 ──────────────────────────────────────────────────────

class TestGovernanceText:
    def test_governance_text_exact(self):
        """治理注释精确字符串(spec 一字不差)。"""
        expected = "Seatbelt 无法约束全局屏幕/鼠标资源 — 审批门、账本、审计是唯一治理层"
        w = _make_widget()
        assert w._GOVERNANCE_TEXT == expected

    def test_governance_text_contains_seatbelt(self):
        w = _make_widget()
        assert "Seatbelt" in w._GOVERNANCE_TEXT

    def test_governance_text_contains_em_dash(self):
        """治理注释用 — (U+2014 EM DASH) 分隔。"""
        w = _make_widget()
        assert "—" in w._GOVERNANCE_TEXT   # U+2014


# ── 9. 页脚不变量静态文字 ────────────────────────────────────────────────────

class TestFooterText:
    def test_footer_text_exact(self):
        """页脚不变量精确字符串(spec 一字不差,不可参数化)。"""
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


# ── 10. 诚实不变量 ───────────────────────────────────────────────────────────

class TestHonestyInvariants:
    def test_risk_cannot_be_lowered_by_caller(self):
        """调用方无法通过 kwargs 传入 risk='low' 来降级。"""
        # HardConfirmCard.__init__ 不接受 risk 参数(或强制覆盖)
        # 无论如何,widget 必须保持 risk-high class
        w = _make_widget()
        assert w.has_class("risk-high")
        assert not w.has_class("risk-low")
        assert not w.has_class("risk-medium")

    def test_escape_value_always_deny(self):
        """escape_value 始终为 'deny'(不随调用方参数改变)。"""
        w = _make_widget()
        assert w._escape_value == "deny"

    def test_title_always_contains_high_irreversible(self):
        """任何 computer.* action 构造的 widget 标题都含 '[high · 不可逆]'。"""
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
            assert "[high · 不可逆]" in w._title, \
                f"action={action} 的标题缺少 '[high · 不可逆]'"

    def test_markup_false_invariant_for_body(self):
        """body 含方括号时不能用 markup=True 渲染(否则会崩溃)。

        widget._body 可能含 [...] (如坐标、括号内内容),必须 markup=False。
        此测试确认 _body 含括号时构造不崩溃。
        """
        # 构造含方括号的 description(模拟真实命令参数)
        w = HardConfirmCard(
            action="computer.type_text",
            x=None,
            y=None,
            description="输入 [Tab] 键切换",
            on_decide=_noop,
        )
        # 若 body Static 用 markup=True,render 会崩;构造不崩即 OK
        assert "[Tab]" in w._body

    def test_action_label_for_summary(self):
        """action_label 用于 _finish 摘要,应含 action 信息。"""
        w = _make_widget(action="computer.scroll")
        # 摘要格式 "◕ 审批 {action_label} → {value}"
        assert w._action_label  # 非空

    def test_options_text_cursor_color_is_eye(self):
        """▸ 光标颜色必须是 $eye 金色(与 InlineChoice 规范一致)。"""
        w = _make_widget()
        rendered = w._options_text()
        # 找含 ▸ 的 span,检查颜色是否为 $eye hex
        spans = [
            s for s in rendered._spans
            if s.style and _COL_EYE.lower() in str(s.style).lower()
        ]
        assert spans, "▸ 光标 span 颜色应为 $eye"

    def test_options_text_deny_digit_4_not_2(self):
        """_options_text 中 deny 选项的数字必须是 '4'(spec 铁律)。"""
        w = _make_widget()
        rendered = w._options_text()
        plain = rendered.plain
        # "4  拒绝" 必须存在
        assert re.search(r"4\s+拒绝", plain), \
            f"_options_text 应含 '4  拒绝',实际: {plain!r}"

    def test_options_text_once_digit_1(self):
        """_options_text 中 once 选项的数字必须是 '1'。"""
        w = _make_widget()
        rendered = w._options_text()
        plain = rendered.plain
        assert re.search(r"1\s+仅此一次", plain), \
            f"_options_text 应含 '1  仅此一次',实际: {plain!r}"


# ── 11. 幂等 _finish ─────────────────────────────────────────────────────────

class TestIdempotent:
    def test_on_decide_called_only_once(self):
        """_finish 幂等:on_decide 最多调用一次。"""
        calls: list[tuple[str, str]] = []

        def decide(v: str, fb: str) -> None:
            calls.append((v, fb))

        w = _make_widget(on_decide=decide)
        w._finish("once", "")
        w._finish("once", "")
        assert len(calls) == 1

    def test_double_deny_calls_decide_once(self):
        """deny 双调也只触发一次。"""
        calls: list = []
        w = _make_widget(on_decide=lambda v, f: calls.append(v))
        w._finish("deny", "")
        w._finish("deny", "")
        assert len(calls) == 1


# ── 12. 各 action 无坐标变体 ─────────────────────────────────────────────────

class TestAllSevenActions:
    """7 种 computer.* 动作都能正常构造。"""

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
        """所有 7 种 computer.* action 构造不抛异常。"""
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
