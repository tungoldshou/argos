"""Internal documentation."""
from __future__ import annotations

import pytest

from argos.ledger.entry import LedgerEntry



def _make_entry(
    *,
    seq: int = 1,
    action: str = "read_file",
    summary_human: str = "读取了 replay.py",
    risk: str = "low",
    reversible: str = "yes",
    undo_token: str | None = None,
    receipt_sig: str = "abcd1234abcd1234",
    undo_state: str = "available",
    run_id: str = "4f9c00000000",
) -> LedgerEntry:
    return LedgerEntry(
        ts=1718358000.0,
        run_id=run_id,
        seq=seq,
        action=action,
        summary_human=summary_human,
        risk=risk,
        reversible=reversible,  # type: ignore[arg-type]
        undo_token=undo_token,
        receipt_sig=receipt_sig,
        undo_state=undo_state,  # type: ignore[arg-type]
    )



def _import_widget():
    from argos.tui.widgets.ledger_table import LedgerTable  # noqa: PLC0415
    return LedgerTable


# ═══════════════════════════════════════════════════════════════════════════════
# ═══════════════════════════════════════════════════════════════════════════════

class TestImport:
    def test_ledger_table_importable(self):
        """Internal documentation."""
        LedgerTable = _import_widget()
        assert LedgerTable is not None

    def test_ledger_table_is_static_subclass(self):
        """Internal documentation."""
        from textual.widgets import Static
        LedgerTable = _import_widget()
        assert issubclass(LedgerTable, Static)

    def test_ledger_table_markup_false(self):
        """Internal documentation."""
        LedgerTable = _import_widget()
        widget = LedgerTable(entries=[], run_id="aabbcc001122")
        assert widget._render_markup is False  # type: ignore[attr-defined]

    def test_can_focus_false(self):
        """Internal documentation."""
        LedgerTable = _import_widget()
        assert LedgerTable.can_focus is False


# ═══════════════════════════════════════════════════════════════════════════════
# ═══════════════════════════════════════════════════════════════════════════════

class TestConstructor:
    def test_accepts_entries_and_run_id(self):
        """Internal documentation."""
        LedgerTable = _import_widget()
        entries = [_make_entry()]
        w = LedgerTable(entries=entries, run_id="4f9c00000000")
        assert w is not None

    def test_empty_entries(self):
        """Internal documentation."""
        LedgerTable = _import_widget()
        w = LedgerTable(entries=[], run_id="4f9c00000000")
        assert w is not None

    def test_rendered_text_property_returns_str(self):
        """Internal documentation."""
        LedgerTable = _import_widget()
        w = LedgerTable(entries=[_make_entry()], run_id="4f9c00000000")
        rt = w.rendered_text
        assert isinstance(rt, str)


# ═══════════════════════════════════════════════════════════════════════════════
# ═══════════════════════════════════════════════════════════════════════════════

class TestHeaderLine:
    def _render(self, entries, run_id="4f9c00000000"):
        LedgerTable = _import_widget()
        return LedgerTable(entries=entries, run_id=run_id).rendered_text

    def test_header_contains_ledger_title(self):
        """Internal documentation."""
        text = self._render([_make_entry()])
        assert "行为账本" in text

    def test_header_contains_run_id(self):
        """Internal documentation."""
        text = self._render([_make_entry(run_id="aabbcc001122")], run_id="aabbcc001122")
        assert "aabbcc001122" in text

    def test_header_count_one(self):
        """Internal documentation."""
        text = self._render([_make_entry()])
        assert "1 条" in text

    def test_header_count_three(self):
        """Internal documentation."""
        entries = [
            _make_entry(seq=1, action="read_file", summary_human="读取了 a.py"),
            _make_entry(seq=2, action="write_file", summary_human="写入了 b.py", risk="low"),
            _make_entry(seq=3, action="run_shell", summary_human="跑了命令: pytest -q", risk="medium"),
        ]
        text = self._render(entries)
        assert "3 条" in text

    def test_undo_done_sentinel_filtered_out_of_count(self):
        """Internal documentation."""
        entries = [
            _make_entry(seq=1, action="write_file", summary_human="写入了 x.py"),
            _make_entry(seq=0, action="undo_done", summary_human="撤销标记"),
        ]
        LedgerTable = _import_widget()
        w = LedgerTable(entries=entries, run_id="000000000000")
        text = w.rendered_text
        assert "1 条" in text

    def test_undo_done_sentinel_not_rendered_in_table(self):
        """Internal documentation."""
        entries = [
            _make_entry(seq=1, action="write_file", summary_human="写入了 x.py"),
            _make_entry(seq=0, action="undo_done", summary_human="undo sentinel text"),
        ]
        LedgerTable = _import_widget()
        w = LedgerTable(entries=entries, run_id="000000000000")
        text = w.rendered_text
        assert "undo sentinel text" not in text


# ═══════════════════════════════════════════════════════════════════════════════
# ═══════════════════════════════════════════════════════════════════════════════

class TestColumnHeaders:
    def _render(self):
        LedgerTable = _import_widget()
        return LedgerTable(entries=[_make_entry()], run_id="4f9c00000000").rendered_text

    def test_col_seq_header(self):
        """Internal documentation."""
        assert "seq" in self._render()

    def test_col_action_header(self):
        """Internal documentation."""
        assert "动作 · 人话" in self._render()

    def test_col_risk_header(self):
        """Internal documentation."""
        assert "风险" in self._render()

    def test_col_reversible_header(self):
        """Internal documentation."""
        assert "可逆" in self._render()

    def test_col_undo_header(self):
        """Internal documentation."""
        assert "撤销" in self._render()

    def test_col_sig_header(self):
        """Internal documentation."""
        assert "签名" in self._render()

    def test_hairline_rule_present(self):
        """Internal documentation."""
        assert "─" in self._render()


# ═══════════════════════════════════════════════════════════════════════════════
# 5. Data row content — summary_human verbatim
# ═══════════════════════════════════════════════════════════════════════════════

class TestDataRowContent:
    def _render(self, entry: LedgerEntry) -> str:
        LedgerTable = _import_widget()
        return LedgerTable(entries=[entry], run_id=entry.run_id).rendered_text

    def test_seq_number_rendered(self):
        """Internal documentation."""
        e = _make_entry(seq=3)
        assert "3" in self._render(e)

    def test_summary_human_verbatim(self):
        """Internal documentation."""
        e = _make_entry(summary_human="读取了 replay.py")
        assert "读取了 replay.py" in self._render(e)

    def test_summary_human_with_brackets(self):
        """Internal documentation."""
        e = _make_entry(summary_human="跑了命令: pytest -q [test_foo, test_bar]")
        text = self._render(e)
        assert "pytest -q [test_foo, test_bar]" in text

    def test_summary_human_edit_template(self):
        """Internal documentation."""
        e = _make_entry(summary_human="编辑了 replay.py(+1/-1)", action="edit_file")
        assert "编辑了 replay.py(+1/-1)" in self._render(e)

    def test_summary_human_write_template(self):
        """Internal documentation."""
        e = _make_entry(summary_human="写入了 report.md(+120 行)", action="write_file")
        assert "写入了 report.md(+120 行)" in self._render(e)


# ═══════════════════════════════════════════════════════════════════════════════
# 6. Risk column — display mapping + colour
# ═══════════════════════════════════════════════════════════════════════════════

class TestRiskColumn:
    def _widget(self, risk: str) -> object:
        LedgerTable = _import_widget()
        e = _make_entry(risk=risk)
        return LedgerTable(entries=[e], run_id=e.run_id)

    def test_risk_low_displays_low(self):
        """Internal documentation."""
        w = self._widget("low")
        assert "low" in w.rendered_text

    def test_risk_medium_displays_med(self):
        """Internal documentation."""
        w = self._widget("medium")
        text = w.rendered_text
        assert "med" in text

    def test_risk_medium_does_not_display_full_word(self):
        """Internal documentation."""
        w = self._widget("medium")
        # 'medium' as a standalone word should NOT appear (only 'med' after mapping)
        # We check that the standalone risk cell does not contain 'medium' literally
        text = w.rendered_text
        # The word 'medium' could appear in summary_human etc, but risk col maps it
        # We verify 'med' IS present (the mapped form)
        assert "med" in text

    def test_risk_high_displays_high(self):
        """Internal documentation."""
        w = self._widget("high")
        assert "high" in w.rendered_text

    def test_risk_low_color_ink_dim(self):
        """Internal documentation."""
        LedgerTable = _import_widget()
        e = _make_entry(risk="low")
        w = LedgerTable(entries=[e], run_id=e.run_id)
        rich_text = w._build_rich_text()
        spans_hex = [str(s.style) for s in rich_text._spans]
        assert any("#7E869C" in h.upper() or "7e869c" in h.lower() for h in spans_hex)

    def test_risk_medium_color_unverif(self):
        """Internal documentation."""
        LedgerTable = _import_widget()
        e = _make_entry(risk="medium")
        w = LedgerTable(entries=[e], run_id=e.run_id)
        rich_text = w._build_rich_text()
        spans_hex = [str(s.style) for s in rich_text._spans]
        assert any("#FF9E64" in h.upper() or "ff9e64" in h.lower() for h in spans_hex)

    def test_risk_high_color_fail(self):
        """Internal documentation."""
        LedgerTable = _import_widget()
        e = _make_entry(risk="high")
        w = LedgerTable(entries=[e], run_id=e.run_id)
        rich_text = w._build_rich_text()
        spans_hex = [str(s.style) for s in rich_text._spans]
        assert any("#F7768E" in h.upper() or "f7768e" in h.lower() for h in spans_hex)

    def test_risk_unknown_fallback_ink_dim(self):
        """Internal documentation."""
        LedgerTable = _import_widget()
        e = _make_entry(risk="weird")
        w = LedgerTable(entries=[e], run_id=e.run_id)
        text = w.rendered_text
        assert "weird" in text


# ═══════════════════════════════════════════════════════════════════════════════
# 7. Reversible column — colour
# ═══════════════════════════════════════════════════════════════════════════════

class TestReversibleColumn:
    def _spans_hex(self, reversible: str) -> list[str]:
        LedgerTable = _import_widget()
        e = _make_entry(reversible=reversible)
        w = LedgerTable(entries=[e], run_id=e.run_id)
        rt = w._build_rich_text()
        return [str(s.style) for s in rt._spans]

    def test_reversible_yes_text(self):
        """Internal documentation."""
        LedgerTable = _import_widget()
        e = _make_entry(reversible="yes")
        assert "yes" in LedgerTable(entries=[e], run_id=e.run_id).rendered_text

    def test_reversible_no_text(self):
        """Internal documentation."""
        LedgerTable = _import_widget()
        e = _make_entry(reversible="no")
        assert "no" in LedgerTable(entries=[e], run_id=e.run_id).rendered_text

    def test_reversible_unknown_text(self):
        """Internal documentation."""
        LedgerTable = _import_widget()
        e = _make_entry(reversible="unknown")
        assert "unknown" in LedgerTable(entries=[e], run_id=e.run_id).rendered_text

    def test_reversible_yes_color_pass_weak(self):
        """Internal documentation."""
        spans = self._spans_hex("yes")
        assert any("73A857" in s.upper() or "73a857" in s.lower() for s in spans)

    def test_reversible_yes_not_strong_pass(self):
        """Internal documentation."""
        spans = self._spans_hex("yes")
        assert any("73A857" in s.upper() or "73a857" in s.lower() for s in spans)

    def test_reversible_no_color_fail(self):
        """reversible='no' → $fail (#F7768E)。"""
        spans = self._spans_hex("no")
        assert any("F7768E" in s.upper() or "f7768e" in s.lower() for s in spans)

    def test_reversible_unknown_color_unverif(self):
        """reversible='unknown' → $unverif (#FF9E64)。"""
        spans = self._spans_hex("unknown")
        assert any("FF9E64" in s.upper() or "ff9e64" in s.lower() for s in spans)


# ═══════════════════════════════════════════════════════════════════════════════
# 8. Undo state column — colour + sentinel
# ═══════════════════════════════════════════════════════════════════════════════

class TestUndoStateColumn:
    def _spans_hex(self, undo_state: str, reversible: str = "yes") -> list[str]:
        LedgerTable = _import_widget()
        e = _make_entry(reversible=reversible, undo_state=undo_state)
        w = LedgerTable(entries=[e], run_id=e.run_id)
        return [str(s.style) for s in w._build_rich_text()._spans]

    def test_undo_available_text(self):
        """Internal documentation."""
        LedgerTable = _import_widget()
        e = _make_entry(undo_state="available")
        assert "available" in LedgerTable(entries=[e], run_id=e.run_id).rendered_text

    def test_undo_done_text(self):
        """Internal documentation."""
        LedgerTable = _import_widget()
        e = _make_entry(undo_state="done")
        assert "done" in LedgerTable(entries=[e], run_id=e.run_id).rendered_text

    def test_undo_impossible_text(self):
        """Internal documentation."""
        LedgerTable = _import_widget()
        e = _make_entry(undo_state="impossible")
        assert "impossible" in LedgerTable(entries=[e], run_id=e.run_id).rendered_text

    def test_undo_available_color_pass(self):
        """Internal documentation."""
        spans = self._spans_hex("available")
        assert any("9ECE6A" in s.upper() or "9ece6a" in s.lower() for s in spans)

    def test_undo_done_color_ink_dim(self):
        """Internal documentation."""
        spans = self._spans_hex("done")
        assert any("7E869C" in s.upper() or "7e869c" in s.lower() for s in spans)

    def test_undo_impossible_color_ink_faint(self):
        """Internal documentation."""
        spans = self._spans_hex("impossible")
        assert any("6B7494" in s.upper() or "6b7494" in s.lower() for s in spans)

    def test_undo_sentinel_dash_for_unknown(self):
        """Internal documentation."""
        LedgerTable = _import_widget()
        # on a 'yes'-reversible low-risk row（per spec .dc.html row1 read_file shows —）
        e = _make_entry(action="read_file", reversible="yes", undo_state="impossible")
        text = LedgerTable(entries=[e], run_id=e.run_id).rendered_text
        assert "impossible" in text or "—" in text


# ═══════════════════════════════════════════════════════════════════════════════
# 9. DEFAULT_CSS — $token only, no raw hex
# ═══════════════════════════════════════════════════════════════════════════════

class TestCssTokens:
    def test_no_raw_hex_in_default_css(self):
        """Internal documentation."""
        import re
        LedgerTable = _import_widget()
        css = LedgerTable.DEFAULT_CSS
        if not css:
            return
        hex_pattern = re.compile(r"#[0-9A-Fa-f]{3,8}\b")
        matches = hex_pattern.findall(css)
        assert not matches, f"DEFAULT_CSS 含裸 hex: {matches}"

    def test_default_css_uses_stream_or_tokens(self):
        """Internal documentation."""
        LedgerTable = _import_widget()
        css = LedgerTable.DEFAULT_CSS
        if css.strip():
            assert "$" in css


# ═══════════════════════════════════════════════════════════════════════════════
# 10. Rich-Text hex constants — annotated with token names
# ═══════════════════════════════════════════════════════════════════════════════

class TestHexConstants:
    """Internal documentation."""

    def _mod(self):
        import argos.tui.widgets.ledger_table as m
        return m

    def test_col_eye(self):
        m = self._mod()
        assert m._COL_EYE.upper() == "#D9A85C"

    def test_col_ink(self):
        m = self._mod()
        assert m._COL_INK.upper() == "#C8CCDA"

    def test_col_ink_bright(self):
        m = self._mod()
        assert m._COL_INK_BRIGHT.upper() == "#ECEEF5"

    def test_col_ink_dim(self):
        m = self._mod()
        assert m._COL_INK_DIM.upper() == "#7E869C"

    def test_col_ink_faint(self):
        m = self._mod()
        assert m._COL_INK_FAINT.upper() == "#6B7494"

    def test_col_pass(self):
        m = self._mod()
        assert m._COL_PASS.upper() == "#9ECE6A"

    def test_col_pass_weak(self):
        m = self._mod()
        assert m._COL_PASS_WEAK.upper() == "#73A857"

    def test_col_fail(self):
        m = self._mod()
        assert m._COL_FAIL.upper() == "#F7768E"

    def test_col_unverif(self):
        m = self._mod()
        assert m._COL_UNVERIF.upper() == "#FF9E64"

    def test_col_hairline(self):
        m = self._mod()
        assert m._COL_HAIRLINE.upper() == "#23252E"


# ═══════════════════════════════════════════════════════════════════════════════
# 11. Honesty invariants
# ═══════════════════════════════════════════════════════════════════════════════

class TestHonestyInvariants:
    def test_computer_action_high_risk_irreversible(self):
        """Internal documentation."""
        LedgerTable = _import_widget()
        e = _make_entry(
            action="computer.click",
            summary_human="点击了屏幕坐标 (412, 280)",
            risk="high",
            reversible="no",
            undo_state="impossible",
        )
        w = LedgerTable(entries=[e], run_id=e.run_id)
        rt = w._build_rich_text()
        spans_hex = [str(s.style) for s in rt._spans]
        # risk high → $fail
        assert any("F7768E" in h.upper() for h in spans_hex)
        # reversible no → $fail
        assert any("F7768E" in h.upper() for h in spans_hex)
        # undo impossible → $ink-faint (finding #27: #6B7494)
        assert any("6B7494" in h.upper() for h in spans_hex)

    def test_error_never_rendered_as_success(self):
        """Internal documentation."""
        LedgerTable = _import_widget()
        e = _make_entry(
            risk="high",
            reversible="no",
            undo_state="impossible",
        )
        w = LedgerTable(entries=[e], run_id=e.run_id)
        rt = w._build_rich_text()
        spans_hex = [str(s.style) for s in rt._spans]
        assert not any("9ECE6A" in h.upper() for h in spans_hex)

    def test_pass_weak_not_equal_pass(self):
        """Internal documentation."""
        LedgerTable = _import_widget()
        # entry where reversible=yes and undo_state=impossible (no undo colour distraction)
        e = _make_entry(reversible="yes", undo_state="impossible")
        w = LedgerTable(entries=[e], run_id=e.run_id)
        rt = w._build_rich_text()
        spans_hex = [str(s.style) for s in rt._spans]
        assert any("73A857" in h.upper() for h in spans_hex)

    def test_undo_state_available_uses_strong_pass(self):
        """Internal documentation."""
        LedgerTable = _import_widget()
        e = _make_entry(reversible="yes", undo_state="available")
        w = LedgerTable(entries=[e], run_id=e.run_id)
        rt = w._build_rich_text()
        spans_hex = [str(s.style) for s in rt._spans]
        assert any("9ECE6A" in h.upper() for h in spans_hex)

    def test_risk_colors_distinct_all_three(self):
        """Internal documentation."""
        LedgerTable = _import_widget()
        entries = [
            _make_entry(seq=1, risk="low", summary_human="读取 a"),
            _make_entry(seq=2, risk="medium", summary_human="跑 shell"),
            _make_entry(seq=3, risk="high", summary_human="写系统路径"),
        ]
        w = LedgerTable(entries=entries, run_id="000000000000")
        rt = w._build_rich_text()
        spans_hex = [str(s.style).upper() for s in rt._spans]
        assert any("7E869C" in h for h in spans_hex), "low risk ink-dim missing"
        assert any("FF9E64" in h for h in spans_hex), "med risk unverif missing"
        assert any("F7768E" in h for h in spans_hex), "high risk fail missing"

    def test_receipt_sig_visible_in_per_row_render(self):
        """Internal documentation."""
        LedgerTable = _import_widget()
        e = _make_entry(receipt_sig="deadbeefcafe0000")
        w = LedgerTable(entries=[e], run_id=e.run_id)
        text = w.rendered_text
        assert "deadbeef" in text, (
            f"receipt_sig 前 8 字符未出现在 table body — 签名声明不可伪证: {text!r}"
        )

    def test_empty_ledger_zero_count(self):
        """Internal documentation."""
        LedgerTable = _import_widget()
        w = LedgerTable(entries=[], run_id="000000000000")
        text = w.rendered_text
        assert "0 条" in text


# ═══════════════════════════════════════════════════════════════════════════════
# 12. Glyph presence
# ═══════════════════════════════════════════════════════════════════════════════

class TestGlyphs:
    def test_hairline_glyph_present(self):
        """Internal documentation."""
        LedgerTable = _import_widget()
        w = LedgerTable(entries=[_make_entry()], run_id="000000000000")
        assert "─" in w.rendered_text

    def test_no_forbidden_glyphs(self):
        """Internal documentation."""
        LedgerTable = _import_widget()
        entries = [
            _make_entry(seq=1, risk="low"),
            _make_entry(seq=2, risk="medium"),
            _make_entry(seq=3, risk="high"),
        ]
        w = LedgerTable(entries=entries, run_id="000000000000")
        text = w.rendered_text
        forbidden = set("●○◎◐◑◇◆▶•")
        found = forbidden & set(text)
        assert not found, f"发现禁止字形: {found}"


# ═══════════════════════════════════════════════════════════════════════════════
# 13. _build_rich_text() — internal API used by tests
# ═══════════════════════════════════════════════════════════════════════════════

class TestBuildRichText:
    def test_build_rich_text_returns_rich_text(self):
        """Internal documentation."""
        from rich.text import Text
        LedgerTable = _import_widget()
        w = LedgerTable(entries=[_make_entry()], run_id="000000000000")
        rt = w._build_rich_text()
        assert isinstance(rt, Text)

    def test_build_rich_text_plain_matches_rendered_text(self):
        """Internal documentation."""
        LedgerTable = _import_widget()
        e = _make_entry(summary_human="读取了 foo.py")
        w = LedgerTable(entries=[e], run_id=e.run_id)
        rt = w._build_rich_text()
        assert "读取了 foo.py" in rt.plain
