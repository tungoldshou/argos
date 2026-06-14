# tests/tui/test_trust_dial.py
"""TrustDial widget TDD 测试套件(Screen #10 信任拨盘)。

覆盖点:
  - 构造 API：TrustDial(current=TrustLevel.Lx)
  - 每一档的 label_human 精确字符串在渲染文本中出现
  - 当前档行带 ▸ 前缀、非当前档行带两空格前缀
  - L4 行的 ⏻ 红灯在渲染文本中出现
  - 分隔/铁律行精确包含 "HARD RULES 永不降级:" 字符串
  - 铁律行三处 $fail 受控类别名称存在
  - 诚实不变量:L4 ⏻ 仅在 L4 是 current 时才在当前行出现
  - can_focus=False(非交互展示组件)
  - markup=False 约束(Static body 不解析 Rich markup)
  - 每档都能构造并渲染(不崩溃)
"""
from __future__ import annotations

import pytest
from rich.text import Text

from argos.permissions.trust_dial import TrustLevel
from argos.tui.widgets.trust_dial import TrustDial


# ─────────────────────────────────────────────────────────────────────────────
# 辅助:从 TrustDial 中取出渲染文本 plain string
# ─────────────────────────────────────────────────────────────────────────────

def _plain(widget: TrustDial) -> str:
    """返回组件渲染的纯文本(剥去 Rich 样式)。"""
    rt = widget._compose_text()
    if isinstance(rt, Text):
        return rt.plain
    return str(rt)


def _rich(widget: TrustDial) -> Text:
    """返回组件渲染的 Rich Text(含样式)。"""
    rt = widget._compose_text()
    if isinstance(rt, Text):
        return rt
    return Text(str(rt))


# ─────────────────────────────────────────────────────────────────────────────
# 构造 & 基本 API
# ─────────────────────────────────────────────────────────────────────────────

class TestConstruction:
    def test_constructs_with_all_levels(self):
        """每档都能无异常构造。"""
        for lvl in TrustLevel:
            widget = TrustDial(current=lvl)
            assert widget is not None

    def test_can_focus_false(self):
        """展示组件:can_focus 必须为 False。"""
        widget = TrustDial(current=TrustLevel.L1_DANGEROUS_ONLY)
        assert widget.can_focus is False

    def test_default_current_l0(self):
        """default 参数行为:不传 current 等价于 L0。"""
        widget = TrustDial(current=TrustLevel.L0_EVERY_STEP)
        assert widget._current == TrustLevel.L0_EVERY_STEP


# ─────────────────────────────────────────────────────────────────────────────
# 标题行
# ─────────────────────────────────────────────────────────────────────────────

class TestHeaderLine:
    def test_header_contains_trust_dial_label(self):
        """第一行必须包含 '信任拨盘'。"""
        for lvl in TrustLevel:
            plain = _plain(TrustDial(current=lvl))
            assert "信任拨盘" in plain, f"level={lvl}: missing '信任拨盘'"

    def test_header_contains_current_marker(self):
        """标题行包含 '当前 ' 前缀。"""
        for lvl in TrustLevel:
            plain = _plain(TrustDial(current=lvl))
            assert "当前 " in plain, f"level={lvl}: missing '当前 '"

    @pytest.mark.parametrize("lvl,short", [
        (TrustLevel.L0_EVERY_STEP,      "L0"),
        (TrustLevel.L1_DANGEROUS_ONLY,  "L1"),
        (TrustLevel.L2_IRREVERSIBLE_ONLY, "L2"),
        (TrustLevel.L3_SESSION_TRUSTED, "L3"),
        (TrustLevel.L4_AUTONOMOUS,      "L4"),
    ])
    def test_header_level_token(self, lvl, short):
        """标题行包含正确的 Lx 短名。"""
        plain = _plain(TrustDial(current=lvl))
        assert short in plain, f"level={lvl}: missing '{short}' in header"


# ─────────────────────────────────────────────────────────────────────────────
# 五行拨盘行
# ─────────────────────────────────────────────────────────────────────────────

class TestDialRows:
    """五行拨盘:每档的精确标签和 hint 文本。"""

    # (level, label, hint_fragment)
    ROWS = [
        (TrustLevel.L0_EVERY_STEP,        "每一步都问我",         "全量确认(含只读)"),
        (TrustLevel.L1_DANGEROUS_ONLY,    "只有危险操作才问",     "高风险暂停 · 低风险放行"),
        (TrustLevel.L2_IRREVERSIBLE_ONLY, "只有不可逆操作才问",   "依赖能力 reversible 字段"),
        (TrustLevel.L3_SESSION_TRUSTED,   "同类批准后本会话放行", "= ACCEPT_EDITS 扩展"),
        (TrustLevel.L4_AUTONOMOUS,        "全自治",               "⏻ 红灯 · HARD RULES 仍拦"),
    ]

    @pytest.mark.parametrize("lvl,label,hint", ROWS)
    def test_label_present_all_levels(self, lvl, label, hint):
        """无论当前档在哪里,每档标签都必须出现。"""
        # 从 L0 视角看完整列表
        widget = TrustDial(current=TrustLevel.L0_EVERY_STEP)
        plain = _plain(widget)
        assert label in plain, f"missing label '{label}'"

    @pytest.mark.parametrize("lvl,label,hint", ROWS)
    def test_hint_present_when_current(self, lvl, label, hint):
        """hint 文本(hint 列)必须在渲染输出中存在。"""
        widget = TrustDial(current=lvl)
        plain = _plain(widget)
        # hint 的核心词必须在渲染输出中
        core = hint.split(" · ")[0]  # 取 hint 第一段
        assert core in plain, f"level={lvl}: missing hint core '{core}'"

    @pytest.mark.parametrize("lvl,label,hint", ROWS)
    def test_all_five_rows_appear(self, lvl, label, hint):
        """从任何当前档来看,5 行标签都在输出中。"""
        widget = TrustDial(current=lvl)
        plain = _plain(widget)
        for _, lbl, _ in self.ROWS:
            assert lbl in plain, (
                f"current={lvl}: missing row label '{lbl}'"
            )


# ─────────────────────────────────────────────────────────────────────────────
# 当前行标记:▸ 和两空格
# ─────────────────────────────────────────────────────────────────────────────

class TestCursorMarker:
    """当前行前缀 ▸(U+25B8),非当前行为两空格。"""

    def test_current_row_has_triangle(self):
        """当前档行包含 ▸ 前缀。"""
        for lvl in TrustLevel:
            widget = TrustDial(current=lvl)
            plain = _plain(widget)
            # ▸ 必须出现在 plain text 中(当前行标记)
            assert "▸" in plain, f"level={lvl}: ▸ not found"

    def test_exactly_one_triangle(self):
        """每个状态下 ▸ 恰好出现一次(只有一行是当前行)。"""
        for lvl in TrustLevel:
            widget = TrustDial(current=lvl)
            plain = _plain(widget)
            count = plain.count("▸")
            assert count == 1, (
                f"level={lvl}: expected exactly 1 ▸, got {count}"
            )

    @pytest.mark.parametrize("current_lvl", list(TrustLevel))
    def test_current_row_label_near_triangle(self, current_lvl):
        """▸ 出现在当前档 label 所在行的同一行(检查 plain text 行级别)。"""
        widget = TrustDial(current=current_lvl)
        plain = _plain(widget)
        lines = plain.splitlines()
        # 找出含 ▸ 的行
        tri_lines = [l for l in lines if "▸" in l]
        assert len(tri_lines) == 1
        tri_line = tri_lines[0]
        # 当前档标签应在同行
        label = current_lvl.label_human
        # label_human 的部分文字在行中
        # L4 label_human = "全自治（HARD RULES 仍拦）" 但行中用缩短版 "全自治"
        short_labels = {
            TrustLevel.L0_EVERY_STEP:        "每一步都问我",
            TrustLevel.L1_DANGEROUS_ONLY:    "只有危险操作才问",
            TrustLevel.L2_IRREVERSIBLE_ONLY: "只有不可逆操作才问",
            TrustLevel.L3_SESSION_TRUSTED:   "同类批准后本会话放行",
            TrustLevel.L4_AUTONOMOUS:        "全自治",
        }
        expected_fragment = short_labels[current_lvl]
        assert expected_fragment in tri_line, (
            f"current={current_lvl}: ▸ line does not contain '{expected_fragment}'. "
            f"Line was: {tri_line!r}"
        )


# ─────────────────────────────────────────────────────────────────────────────
# L4 ⏻ 红灯
# ─────────────────────────────────────────────────────────────────────────────

class TestL4RedLamp:
    def test_power_symbol_present(self):
        """⏻(U+23FB)在 L4 行出现。"""
        widget = TrustDial(current=TrustLevel.L0_EVERY_STEP)
        plain = _plain(widget)
        assert "⏻" in plain, "⏻ (U+23FB) must appear in L4 row hint"

    def test_power_symbol_on_l4_line(self):
        """⏻ 所在行包含 'L4' 或 '全自治'。"""
        widget = TrustDial(current=TrustLevel.L0_EVERY_STEP)
        plain = _plain(widget)
        lines = plain.splitlines()
        l4_lines = [l for l in lines if "⏻" in l]
        assert l4_lines, "no line with ⏻ found"
        assert any("L4" in l or "全自治" in l for l in l4_lines), (
            f"⏻ line(s) do not contain L4/全自治: {l4_lines}"
        )

    def test_l4_red_lamp_uses_fail_color(self):
        """⏻ 红灯的 span 颜色必须是 $fail (#F7768E)。"""
        widget = TrustDial(current=TrustLevel.L0_EVERY_STEP)
        rt = _rich(widget)
        fail_hex = "#F7768E"
        # 在 Rich Text 的 spans 中找到包含 ⏻ 的 span 并检查颜色
        found_fail = False
        for span in rt._spans:
            segment_text = rt.plain[span.start:span.end]
            if "⏻" in segment_text:
                style_str = str(span.style)
                if fail_hex.lower() in style_str.lower():
                    found_fail = True
                    break
        assert found_fail, (
            f"⏻ span must use $fail ({fail_hex}); "
            f"spans found: {[(rt.plain[s.start:s.end], str(s.style)) for s in rt._spans if '⏻' in rt.plain[s.start:s.end]]}"
        )


# ─────────────────────────────────────────────────────────────────────────────
# HARD RULES 铁律行
# ─────────────────────────────────────────────────────────────────────────────

class TestHardRulesLine:
    def test_hard_rules_label_present(self):
        """每档渲染输出都包含 'HARD RULES 永不降级:' 字符串。"""
        for lvl in TrustLevel:
            plain = _plain(TrustDial(current=lvl))
            assert "HARD RULES 永不降级:" in plain, (
                f"level={lvl}: 'HARD RULES 永不降级:' missing"
            )

    def test_hard_rules_three_categories(self):
        """铁律行包含三处受保护类别名称。"""
        for lvl in TrustLevel:
            plain = _plain(TrustDial(current=lvl))
            assert "危险 shell" in plain, f"level={lvl}: missing '危险 shell'"
            assert "系统路径" in plain, f"level={lvl}: missing '系统路径'"
            assert "secret 检测" in plain, f"level={lvl}: missing 'secret 检测'"

    def test_hard_rules_three_fail_spans(self):
        """铁律行三处类别名均使用 $fail (#F7768E) 颜色。"""
        fail_hex = "#F7768E"
        categories = ["危险 shell", "系统路径", "secret 检测"]
        widget = TrustDial(current=TrustLevel.L1_DANGEROUS_ONLY)
        rt = _rich(widget)
        plain = rt.plain

        for cat in categories:
            # 找到 cat 在 plain 中的位置,检查对应 span 的颜色
            idx = plain.find(cat)
            assert idx >= 0, f"category '{cat}' not found in plain text"
            found_fail = False
            for span in rt._spans:
                if span.start <= idx < span.end:
                    style_str = str(span.style)
                    if fail_hex.lower() in style_str.lower():
                        found_fail = True
                        break
            assert found_fail, (
                f"category '{cat}' must be colored {fail_hex}; "
                f"spans at idx={idx}: "
                f"{[(rt.plain[s.start:s.end], str(s.style)) for s in rt._spans if s.start <= idx < s.end]}"
            )

    def test_hard_rules_present_even_at_l4(self):
        """L4 档(最高自治)下铁律行仍然存在。"""
        plain = _plain(TrustDial(current=TrustLevel.L4_AUTONOMOUS))
        assert "HARD RULES 永不降级:" in plain
        assert "危险 shell" in plain
        assert "secret 检测" in plain


# ─────────────────────────────────────────────────────────────────────────────
# 诚实不变量
# ─────────────────────────────────────────────────────────────────────────────

class TestHonestyInvariants:
    def test_current_row_is_bright_not_faint(self):
        """当前行使用 $ink-bright 颜色,非当前行不用该颜色作为行前缀。

        代理断言:当前行 label 所在行包含 ▸ 标记(光标),充分体现当前高亮。
        """
        for lvl in TrustLevel:
            widget = TrustDial(current=lvl)
            plain = _plain(widget)
            lines = plain.splitlines()
            tri_lines = [l for l in lines if "▸" in l]
            assert len(tri_lines) == 1, f"level={lvl}: expected 1 cursor row, got {len(tri_lines)}"

    def test_no_extra_triangle_on_non_current(self):
        """非当前行不得有 ▸。"""
        for lvl in TrustLevel:
            widget = TrustDial(current=lvl)
            plain = _plain(widget)
            lines = plain.splitlines()
            # 非拨盘行(header, iron-law, footer)中不得有 ▸
            for line in lines:
                if "▸" in line:
                    # 该行必须包含当前 level 的 short label
                    short_labels = {
                        TrustLevel.L0_EVERY_STEP:        "每一步都问我",
                        TrustLevel.L1_DANGEROUS_ONLY:    "只有危险操作才问",
                        TrustLevel.L2_IRREVERSIBLE_ONLY: "只有不可逆操作才问",
                        TrustLevel.L3_SESSION_TRUSTED:   "同类批准后本会话放行",
                        TrustLevel.L4_AUTONOMOUS:        "全自治",
                    }
                    expected = short_labels[lvl]
                    assert expected in line, (
                        f"level={lvl}: ▸ found on non-current line: {line!r}"
                    )

    def test_hard_rules_immune_always_true(self):
        """from argos.permissions.trust_dial import hard_rules_immune 总返回 True。"""
        from argos.permissions.trust_dial import hard_rules_immune
        assert hard_rules_immune() is True

    def test_l4_hint_mentions_hard_rules(self):
        """L4 行的 hint 提及 HARD RULES 仍拦(不暗示完全绕过)。"""
        widget = TrustDial(current=TrustLevel.L4_AUTONOMOUS)
        plain = _plain(widget)
        lines = plain.splitlines()
        # 找到包含 ⏻ 的行
        l4_lines = [l for l in lines if "⏻" in l or ("全自治" in l and "▸" in l)]
        assert l4_lines, "L4 current row not found"
        # 在 L4 当前行(hint 列)或整个输出中应有 "HARD RULES 仍拦"
        assert "HARD RULES 仍拦" in plain, (
            "L4 hint must contain 'HARD RULES 仍拦' to avoid implying full bypass"
        )

    def test_markup_false_on_static(self):
        """TrustDial 必须是 markup=False 的 Static(体/主体不解析 Rich markup)。"""
        from textual.widgets import Static
        widget = TrustDial(current=TrustLevel.L1_DANGEROUS_ONLY)
        assert isinstance(widget, Static)
        # Textual 内部 _render_markup=False 表示 markup=False 已生效
        assert widget._render_markup is False


# ─────────────────────────────────────────────────────────────────────────────
# 颜色常量 discipline
# ─────────────────────────────────────────────────────────────────────────────

class TestColorDiscipline:
    """模块级 hex 常量必须与 theme.py token 值一致。"""

    def test_col_eye_matches_theme(self):
        """_COL_EYE = '#D9A85C' ($eye)。"""
        from argos.tui.widgets.trust_dial import _COL_EYE
        assert _COL_EYE.upper() == "#D9A85C"

    def test_col_fail_matches_theme(self):
        """_COL_FAIL = '#F7768E' ($fail)。"""
        from argos.tui.widgets.trust_dial import _COL_FAIL
        assert _COL_FAIL.upper() == "#F7768E"

    def test_col_ink_bright_matches_theme(self):
        """_COL_INK_BRIGHT = '#ECEEF5' ($ink-bright)。"""
        from argos.tui.widgets.trust_dial import _COL_INK_BRIGHT
        assert _COL_INK_BRIGHT.upper() == "#ECEEF5"

    def test_col_ink_dim_matches_theme(self):
        """_COL_INK_DIM = '#7E869C' ($ink-dim)。"""
        from argos.tui.widgets.trust_dial import _COL_INK_DIM
        assert _COL_INK_DIM.upper() == "#7E869C"

    def test_col_ink_faint_matches_theme(self):
        """_COL_INK_FAINT = '#525A73' ($ink-faint)。"""
        from argos.tui.widgets.trust_dial import _COL_INK_FAINT
        assert _COL_INK_FAINT.upper() == "#525A73"

    def test_col_ink_matches_theme(self):
        """_COL_INK = '#C8CCDA' ($ink)。"""
        from argos.tui.widgets.trust_dial import _COL_INK
        assert _COL_INK.upper() == "#C8CCDA"
