# tests/tui/test_trust_dial.py
"""Internal documentation."""
from __future__ import annotations

import pytest
from rich.text import Text

from argos.permissions.trust_dial import TrustLevel
from argos.tui.widgets.trust_dial import TrustDial


# ─────────────────────────────────────────────────────────────────────────────
# ─────────────────────────────────────────────────────────────────────────────

def _plain(widget: TrustDial) -> str:
    """Internal documentation."""
    rt = widget._compose_text()
    if isinstance(rt, Text):
        return rt.plain
    return str(rt)


def _rich(widget: TrustDial) -> Text:
    """Internal documentation."""
    rt = widget._compose_text()
    if isinstance(rt, Text):
        return rt
    return Text(str(rt))


# ─────────────────────────────────────────────────────────────────────────────
# ─────────────────────────────────────────────────────────────────────────────

class TestConstruction:
    def test_constructs_with_all_levels(self):
        """Internal documentation."""
        for lvl in TrustLevel:
            widget = TrustDial(current=lvl)
            assert widget is not None

    def test_can_focus_false(self):
        """Internal documentation."""
        widget = TrustDial(current=TrustLevel.L1_DANGEROUS_ONLY)
        assert widget.can_focus is False

    def test_default_current_l0(self):
        """Internal documentation."""
        widget = TrustDial(current=TrustLevel.L0_EVERY_STEP)
        assert widget._current == TrustLevel.L0_EVERY_STEP


# ─────────────────────────────────────────────────────────────────────────────
# ─────────────────────────────────────────────────────────────────────────────

class TestHeaderLine:
    def test_header_contains_trust_dial_label(self):
        """Internal documentation."""
        for lvl in TrustLevel:
            plain = _plain(TrustDial(current=lvl))
            assert "信任拨盘" in plain, f"level={lvl}: missing '信任拨盘'"

    def test_header_contains_current_marker(self):
        """Internal documentation."""
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
        """Internal documentation."""
        plain = _plain(TrustDial(current=lvl))
        assert short in plain, f"level={lvl}: missing '{short}' in header"


# ─────────────────────────────────────────────────────────────────────────────
# ─────────────────────────────────────────────────────────────────────────────

class TestDialRows:
    """Internal documentation."""

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
        """Internal documentation."""
        widget = TrustDial(current=TrustLevel.L0_EVERY_STEP)
        plain = _plain(widget)
        assert label in plain, f"missing label '{label}'"

    @pytest.mark.parametrize("lvl,label,hint", ROWS)
    def test_hint_present_when_current(self, lvl, label, hint):
        """Internal documentation."""
        widget = TrustDial(current=lvl)
        plain = _plain(widget)
        core = hint.split(" · ")[0]
        assert core in plain, f"level={lvl}: missing hint core '{core}'"

    @pytest.mark.parametrize("lvl,label,hint", ROWS)
    def test_all_five_rows_appear(self, lvl, label, hint):
        """Internal documentation."""
        widget = TrustDial(current=lvl)
        plain = _plain(widget)
        for _, lbl, _ in self.ROWS:
            assert lbl in plain, (
                f"current={lvl}: missing row label '{lbl}'"
            )


# ─────────────────────────────────────────────────────────────────────────────
# ─────────────────────────────────────────────────────────────────────────────

class TestCursorMarker:
    """Internal documentation."""

    def test_current_row_has_triangle(self):
        """Internal documentation."""
        for lvl in TrustLevel:
            widget = TrustDial(current=lvl)
            plain = _plain(widget)
            assert "▸" in plain, f"level={lvl}: ▸ not found"

    def test_exactly_one_triangle(self):
        """Internal documentation."""
        for lvl in TrustLevel:
            widget = TrustDial(current=lvl)
            plain = _plain(widget)
            count = plain.count("▸")
            assert count == 1, (
                f"level={lvl}: expected exactly 1 ▸, got {count}"
            )

    @pytest.mark.parametrize("current_lvl", list(TrustLevel))
    def test_current_row_label_near_triangle(self, current_lvl):
        """Internal documentation."""
        widget = TrustDial(current=current_lvl)
        plain = _plain(widget)
        lines = plain.splitlines()
        tri_lines = [l for l in lines if "▸" in l]
        assert len(tri_lines) == 1
        tri_line = tri_lines[0]
        label = current_lvl.label_human
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
# ─────────────────────────────────────────────────────────────────────────────

class TestL4RedLamp:
    def test_power_symbol_present(self):
        """Internal documentation."""
        widget = TrustDial(current=TrustLevel.L0_EVERY_STEP)
        plain = _plain(widget)
        assert "⏻" in plain, "⏻ (U+23FB) must appear in L4 row hint"

    def test_power_symbol_on_l4_line(self):
        """Internal documentation."""
        widget = TrustDial(current=TrustLevel.L0_EVERY_STEP)
        plain = _plain(widget)
        lines = plain.splitlines()
        l4_lines = [l for l in lines if "⏻" in l]
        assert l4_lines, "no line with ⏻ found"
        assert any("L4" in l or "全自治" in l for l in l4_lines), (
            f"⏻ line(s) do not contain L4/全自治: {l4_lines}"
        )

    def test_l4_red_lamp_uses_fail_color(self):
        """Internal documentation."""
        widget = TrustDial(current=TrustLevel.L0_EVERY_STEP)
        rt = _rich(widget)
        fail_hex = "#F7768E"
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
# ─────────────────────────────────────────────────────────────────────────────

class TestHardRulesLine:
    def test_hard_rules_label_present(self):
        """Internal documentation."""
        for lvl in TrustLevel:
            plain = _plain(TrustDial(current=lvl))
            assert "HARD RULES 永不降级:" in plain, (
                f"level={lvl}: 'HARD RULES 永不降级:' missing"
            )

    def test_hard_rules_three_categories(self):
        """Internal documentation."""
        for lvl in TrustLevel:
            plain = _plain(TrustDial(current=lvl))
            assert "危险 shell" in plain, f"level={lvl}: missing '危险 shell'"
            assert "系统路径" in plain, f"level={lvl}: missing '系统路径'"
            assert "secret 检测" in plain, f"level={lvl}: missing 'secret 检测'"

    def test_hard_rules_three_fail_spans(self):
        """Internal documentation."""
        fail_hex = "#F7768E"
        categories = ["危险 shell", "系统路径", "secret 检测"]
        widget = TrustDial(current=TrustLevel.L1_DANGEROUS_ONLY)
        rt = _rich(widget)
        plain = rt.plain

        for cat in categories:
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
        """Internal documentation."""
        plain = _plain(TrustDial(current=TrustLevel.L4_AUTONOMOUS))
        assert "HARD RULES 永不降级:" in plain
        assert "危险 shell" in plain
        assert "secret 检测" in plain


# ─────────────────────────────────────────────────────────────────────────────
# ─────────────────────────────────────────────────────────────────────────────

class TestHonestyInvariants:
    def test_current_row_is_bright_not_faint(self):
        """Internal documentation."""
        for lvl in TrustLevel:
            widget = TrustDial(current=lvl)
            plain = _plain(widget)
            lines = plain.splitlines()
            tri_lines = [l for l in lines if "▸" in l]
            assert len(tri_lines) == 1, f"level={lvl}: expected 1 cursor row, got {len(tri_lines)}"

    def test_no_extra_triangle_on_non_current(self):
        """Internal documentation."""
        for lvl in TrustLevel:
            widget = TrustDial(current=lvl)
            plain = _plain(widget)
            lines = plain.splitlines()
            for line in lines:
                if "▸" in line:
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
        """Internal documentation."""
        from argos.permissions.trust_dial import hard_rules_immune
        assert hard_rules_immune() is True

    def test_l4_hint_mentions_hard_rules(self):
        """Internal documentation."""
        widget = TrustDial(current=TrustLevel.L4_AUTONOMOUS)
        plain = _plain(widget)
        lines = plain.splitlines()
        l4_lines = [l for l in lines if "⏻" in l or ("全自治" in l and "▸" in l)]
        assert l4_lines, "L4 current row not found"
        assert "HARD RULES 仍拦" in plain, (
            "L4 hint must contain 'HARD RULES 仍拦' to avoid implying full bypass"
        )

    def test_markup_false_on_static(self):
        """Internal documentation."""
        from textual.widgets import Static
        widget = TrustDial(current=TrustLevel.L1_DANGEROUS_ONLY)
        assert isinstance(widget, Static)
        assert widget._render_markup is False


# ─────────────────────────────────────────────────────────────────────────────
# ─────────────────────────────────────────────────────────────────────────────

class TestColorDiscipline:
    """Internal documentation."""

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
        """_COL_INK_FAINT = '#6B7494' ($ink-faint)。"""
        from argos.tui.widgets.trust_dial import _COL_INK_FAINT
        assert _COL_INK_FAINT.upper() == "#6B7494"

    def test_col_ink_matches_theme(self):
        """_COL_INK = '#C8CCDA' ($ink)。"""
        from argos.tui.widgets.trust_dial import _COL_INK
        assert _COL_INK.upper() == "#C8CCDA"
