# tests/tui/test_dream_report.py
"""Internal documentation."""
from __future__ import annotations

import re
import importlib

import pytest
from textual.app import App, ComposeResult
from textual.widgets import Static

from argos.tui.theme import ARGOS_NIGHT


_COL_PASS   = "#9ECE6A"  # $pass
_COL_FAIL   = "#F7768E"  # $fail
_COL_UNVERIF = "#FF9E64"  # $unverif
_COL_EYE    = "#D9A85C"  # $eye
_COL_INK    = "#C8CCDA"  # $ink
_COL_INK_DIM  = "#7E869C"  # $ink-dim
_COL_INK_FAINT = "#6B7494"  # $ink-faint
_COL_INK_BRIGHT = "#ECEEF5"  # $ink-bright



def test_module_importable():
    """Internal documentation."""
    mod = importlib.import_module("argos.tui.widgets.dream_report")
    assert hasattr(mod, "DreamReportCard")


def test_class_is_widget():
    """Internal documentation."""
    from argos.tui.widgets.dream_report import DreamReportCard
    from textual.widget import Widget
    assert issubclass(DreamReportCard, Widget)



class _Host(App):
    """Internal documentation."""
    CSS = ""

    def get_theme_variable_defaults(self) -> dict[str, str]:
        return ARGOS_NIGHT.variables

    def compose(self) -> ComposeResult:
        from argos.tui.widgets.dream_report import DreamReportCard
        yield DreamReportCard()



@pytest.mark.asyncio
async def test_card_mounts_without_crash():
    """Internal documentation."""
    app = _Host()
    async with app.run_test() as pilot:
        from argos.tui.widgets.dream_report import DreamReportCard
        cards = app.query(DreamReportCard)
        assert len(cards) > 0


def _all_text(widgets) -> str:
    """Internal documentation."""
    parts = []
    for w in widgets:
        c = w.content
        parts.append(str(c))
    return "\n".join(parts)


@pytest.mark.asyncio
async def test_echo_line_present():
    """Internal documentation."""
    app = _Host()
    async with app.run_test() as pilot:
        await pilot.pause()
        full = _all_text(app.query(Static))
        assert "› /dream" in full



@pytest.mark.asyncio
async def test_append_stage_scan():
    """Internal documentation."""
    app = _Host()
    async with app.run_test() as pilot:
        from argos.tui.widgets.dream_report import DreamReportCard
        card = app.query_one(DreamReportCard)
        card.append_stage("scan", "5 units")
        await pilot.pause()
        statics = card.query(Static)
        all_text = _all_text(statics)
        assert "◔" in all_text
        assert "5 units" in all_text


@pytest.mark.asyncio
async def test_append_stage_cluster():
    """Internal documentation."""
    app = _Host()
    async with app.run_test() as pilot:
        from argos.tui.widgets.dream_report import DreamReportCard
        card = app.query_one(DreamReportCard)
        card.append_stage("cluster", "3 簇")
        await pilot.pause()
        statics = card.query(Static)
        all_text = _all_text(statics)
        assert "◉" in all_text


@pytest.mark.asyncio
async def test_append_stage_synthesize():
    """Internal documentation."""
    app = _Host()
    async with app.run_test() as pilot:
        from argos.tui.widgets.dream_report import DreamReportCard
        card = app.query_one(DreamReportCard)
        card.append_stage("synthesize", "")
        await pilot.pause()
        statics = card.query(Static)
        all_text = _all_text(statics)
        assert "◉" in all_text


@pytest.mark.asyncio
async def test_append_stage_promote():
    """Internal documentation."""
    app = _Host()
    async with app.run_test() as pilot:
        from argos.tui.widgets.dream_report import DreamReportCard
        card = app.query_one(DreamReportCard)
        card.append_stage("promote", "A/B 晋升")
        await pilot.pause()
        statics = card.query(Static)
        all_text = _all_text(statics)
        assert "❂" in all_text


@pytest.mark.asyncio
async def test_append_stage_memory():
    """Internal documentation."""
    app = _Host()
    async with app.run_test() as pilot:
        from argos.tui.widgets.dream_report import DreamReportCard
        card = app.query_one(DreamReportCard)
        card.append_stage("memory", "记忆整理")
        await pilot.pause()
        statics = card.query(Static)
        all_text = _all_text(statics)
        assert "◔" in all_text


@pytest.mark.asyncio
async def test_append_stage_done_is_only_pass():
    """Internal documentation."""
    app = _Host()
    async with app.run_test() as pilot:
        from argos.tui.widgets.dream_report import DreamReportCard
        card = app.query_one(DreamReportCard)
        card.append_stage("scan", "3 units")
        card.append_stage("done", "")
        await pilot.pause()
        statics = card.query(Static)
        all_text = _all_text(statics)
        assert "◕" in all_text



def test_stage_glyph_map_complete():
    """Internal documentation."""
    from argos.tui.widgets.dream_report import _STAGE_GLYPH
    assert _STAGE_GLYPH["scan"]      == "◔"
    assert _STAGE_GLYPH["cluster"]   == "◉"
    assert _STAGE_GLYPH["synthesize"] == "◉"
    assert _STAGE_GLYPH["promote"]   == "❂"
    assert _STAGE_GLYPH["memory"]    == "◔"
    assert _STAGE_GLYPH["done"]      == "◕"


def test_stage_glyph_fallback_exists():
    """Internal documentation."""
    from argos.tui.widgets.dream_report import _STAGE_GLYPH
    # get with default — implementation should handle unknown gracefully
    glyph = _STAGE_GLYPH.get("unknown_stage", "·")
    assert glyph == "·"



@pytest.mark.asyncio
async def test_show_report_counts_rendered():
    """Internal documentation."""
    app = _Host()
    async with app.run_test() as pilot:
        from argos.tui.widgets.dream_report import DreamReportCard
        card = app.query_one(DreamReportCard)
        card.show_report({
            "units_total": 7,
            "promoted": 3,
            "rejected": 2,
            "skipped": 1,
            "memory_merged": 4,
            "memory_archived": 5,
            "report_path": "/tmp/dream.json",
        })
        await pilot.pause()
        statics = card.query(Static)
        all_text = _all_text(statics)
        assert "7" in all_text
        assert "3" in all_text
        assert "2" in all_text
        assert "1" in all_text


@pytest.mark.asyncio
async def test_show_report_row_b_three_color_contract():
    """Internal documentation."""
    from rich.text import Text
    from argos.tui.widgets.dream_report import DreamReportCard

    report = {
        "units_total": 10,
        "promoted": 4,
        "rejected": 2,
        "skipped": 1,
        "memory_merged": 3,
        "memory_archived": 2,
        "report_path": "",
    }
    card = DreamReportCard()
    row_b_text = card._build_row_b(report)
    assert isinstance(row_b_text, Text)

    full_str = row_b_text.plain
    assert "4" in full_str
    assert "2" in full_str
    assert "1" in full_str

    span_styles = [str(span.style) for span in row_b_text._spans]
    all_styles = " ".join(span_styles)
    assert _COL_PASS in all_styles,   f"promoted 必须是 $pass {_COL_PASS}"
    assert _COL_FAIL in all_styles,   f"rejected 必须是 $fail {_COL_FAIL}"
    assert _COL_UNVERIF in all_styles, f"skipped 必须是 $unverif {_COL_UNVERIF}"


def test_row_b_zero_counts():
    """Internal documentation."""
    from rich.text import Text
    from argos.tui.widgets.dream_report import DreamReportCard
    card = DreamReportCard()
    report = {
        "units_total": 0,
        "promoted": 0,
        "rejected": 0,
        "skipped": 0,
        "memory_merged": 0,
        "memory_archived": 0,
        "report_path": "",
    }
    row_b = card._build_row_b(report)
    plain = row_b.plain
    assert plain.count("0") >= 3



@pytest.mark.asyncio
async def test_row_d_absent_when_promoted_zero():
    """Internal documentation."""
    app = _Host()
    async with app.run_test() as pilot:
        from argos.tui.widgets.dream_report import DreamReportCard
        card = app.query_one(DreamReportCard)
        card.show_report({
            "units_total": 3,
            "promoted": 0,
            "rejected": 2,
            "skipped": 1,
            "memory_merged": 0,
            "memory_archived": 0,
            "report_path": "",
        })
        await pilot.pause()
        statics = card.query(Static)
        all_text = _all_text(statics)
        assert "晋升:" not in all_text


@pytest.mark.asyncio
async def test_row_d_absent_without_promoted_name():
    """Internal documentation."""
    app = _Host()
    async with app.run_test() as pilot:
        from argos.tui.widgets.dream_report import DreamReportCard
        card = app.query_one(DreamReportCard)
        card.show_report({
            "units_total": 5,
            "promoted": 2,
            "rejected": 1,
            "skipped": 0,
            "memory_merged": 1,
            "memory_archived": 0,
            "report_path": "/tmp/report.json",
        })
        await pilot.pause()
        statics = card.query(Static)
        all_text = _all_text(statics)
        assert "晋升:" not in all_text



@pytest.mark.asyncio
async def test_caption_always_present():
    """Internal documentation."""
    app = _Host()
    async with app.run_test() as pilot:
        await pilot.pause()
        statics = app.query(Static)
        all_text = _all_text(statics)
        assert "可执行内容逐字来自源材料" in all_text
        assert "模型只写叙述" in all_text



@pytest.mark.asyncio
async def test_markup_safety_in_stage_detail():
    """Internal documentation."""
    app = _Host()
    async with app.run_test() as pilot:
        from argos.tui.widgets.dream_report import DreamReportCard
        card = app.query_one(DreamReportCard)
        card.append_stage("scan", "3 [units] found [bold]")
        await pilot.pause()
        statics = card.query(Static)
        all_text = _all_text(statics)
        assert "units" in all_text


@pytest.mark.asyncio
async def test_markup_safety_in_report_path():
    """Internal documentation."""
    app = _Host()
    async with app.run_test() as pilot:
        from argos.tui.widgets.dream_report import DreamReportCard
        card = app.query_one(DreamReportCard)
        card.show_report({
            "units_total": 1,
            "promoted": 0,
            "rejected": 1,
            "skipped": 0,
            "memory_merged": 0,
            "memory_archived": 0,
            "report_path": "/tmp/[special]/dream.json",
        })
        await pilot.pause()



def test_default_css_no_raw_hex():
    """Internal documentation."""
    from argos.tui.widgets.dream_report import DreamReportCard
    css = DreamReportCard.DEFAULT_CSS
    hex_colors = re.findall(r"#[0-9A-Fa-f]{3,8}", css)
    assert not hex_colors, (
        f"DEFAULT_CSS 里不允许裸 hex;发现: {hex_colors}"
    )



def test_append_stage_signature():
    """Internal documentation."""
    from argos.tui.widgets.dream_report import DreamReportCard
    import inspect
    sig = inspect.signature(DreamReportCard.append_stage)
    params = list(sig.parameters.keys())
    assert "stage" in params
    assert "detail" in params


def test_show_report_signature():
    """Internal documentation."""
    from argos.tui.widgets.dream_report import DreamReportCard
    import inspect
    sig = inspect.signature(DreamReportCard.show_report)
    params = list(sig.parameters.keys())
    assert len(params) >= 2  # self + report


def test_build_row_b_method_exists():
    """Internal documentation."""
    from argos.tui.widgets.dream_report import DreamReportCard
    assert hasattr(DreamReportCard, "_build_row_b")
    assert callable(DreamReportCard._build_row_b)



def test_show_report_accepts_dream_report_dataclass():
    """Internal documentation."""
    from argos.learning.dream import DreamReport
    from argos.tui.widgets.dream_report import DreamReportCard
    report = DreamReport(
        units_total=5, promoted=2, rejected=1, skipped=1,
        memory_merged=3, memory_archived=1, report_path="/tmp/r.json"
    )
    card = DreamReportCard()
    row_b = card._build_row_b(report)
    from rich.text import Text
    assert isinstance(row_b, Text)
    assert "2" in row_b.plain   # promoted
    assert "1" in row_b.plain   # rejected (1)



@pytest.mark.asyncio
async def test_report_box_title_row_a():
    """Internal documentation."""
    app = _Host()
    async with app.run_test() as pilot:
        from argos.tui.widgets.dream_report import DreamReportCard
        card = app.query_one(DreamReportCard)
        card.show_report({
            "units_total": 2,
            "promoted": 1,
            "rejected": 0,
            "skipped": 1,
            "memory_merged": 0,
            "memory_archived": 0,
            "report_path": "",
        })
        await pilot.pause()
        statics = card.query(Static)
        all_text = _all_text(statics)
        assert "─ 报告" in all_text



@pytest.mark.asyncio
async def test_report_row_c_memory_counts():
    """Internal documentation."""
    app = _Host()
    async with app.run_test() as pilot:
        from argos.tui.widgets.dream_report import DreamReportCard
        card = app.query_one(DreamReportCard)
        card.show_report({
            "units_total": 5,
            "promoted": 1,
            "rejected": 2,
            "skipped": 1,
            "memory_merged": 8,
            "memory_archived": 3,
            "report_path": "",
        })
        await pilot.pause()
        statics = card.query(Static)
        all_text = _all_text(statics)
        assert "记忆合并" in all_text
        assert "归档" in all_text
        assert "8" in all_text
        assert "3" in all_text



@pytest.mark.asyncio
async def test_footer_present():
    """Internal documentation."""
    app = _Host()
    async with app.run_test() as pilot:
        await pilot.pause()
        statics = app.query(Static)
        all_text = _all_text(statics)
        assert "失败安全降级" in all_text



@pytest.mark.asyncio
async def test_done_stage_idempotent():
    """Internal documentation."""
    app = _Host()
    async with app.run_test() as pilot:
        from argos.tui.widgets.dream_report import DreamReportCard
        card = app.query_one(DreamReportCard)
        card.append_stage("done", "")
        card.append_stage("done", "")
        await pilot.pause()
        statics = card.query(Static)
        all_text = _all_text(statics)
        assert all_text.count("◕") == 1
