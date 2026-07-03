# tests/tui/test_tab_strip.py
from __future__ import annotations

import pytest

from argos.tui.widgets.tab_strip import TabStrip, _STATE_ICON, _format_cost, _COL_FAIL, _truncate, _cell_len


# ─────────────────────────────────────────────────────────────────────────────
# helpers
# ─────────────────────────────────────────────────────────────────────────────

def _strip() -> TabStrip:
    return TabStrip()


def _render(tabs: list[dict], active: str | None = None) -> str:
    s = _strip()
    s.update_tabs(tabs, active=active)
    return s.render()


# ─────────────────────────────────────────────────────────────────────────────
# [MEDIUM] border-bottom hairline in DEFAULT_CSS
# ─────────────────────────────────────────────────────────────────────────────

class TestDefaultCss:
    def test_border_bottom_hairline_present(self):
        css = TabStrip.DEFAULT_CSS
        assert "border-bottom" in css, "DEFAULT_CSS 缺少 border-bottom"
        assert "$hairline" in css, "border-bottom 必须使用 $hairline token,不得硬编码 hex"
        assert "solid" in css or "hkey" in css,\
            "border-bottom 应为 solid $hairline 或 hkey $hairline"

    def test_background_uses_well_token(self):
        assert "$well" in TabStrip.DEFAULT_CSS

    def test_color_uses_ink_dim_token(self):
        assert "$ink-dim" in TabStrip.DEFAULT_CSS


# ─────────────────────────────────────────────────────────────────────────────
# ─────────────────────────────────────────────────────────────────────────────

class TestFailedGlyphColor:
    def test_non_active_failed_tab_glyph_colored_fail(self):
        tabs = [
            {"run_id": "r1", "goal": "task one", "state": "failed", "cost_usd": 0.05},
        ]
        rendered = _render(tabs, active=None)
        assert _COL_FAIL in rendered,\
            f"render() 中非活跃 failed tab 未找到 $fail ({_COL_FAIL}) 颜色标记"
        assert "◉" in rendered

    def test_non_active_failed_tab_has_fail_markup_around_glyph(self):
        tabs = [
            {"run_id": "r1", "goal": "my task", "state": "failed", "cost_usd": 0.02},
        ]
        rendered = _render(tabs, active=None)
        assert f"[{_COL_FAIL}]◉" in rendered or f"[{_COL_FAIL}]◉" in rendered,\
            "◉ 字形应紧跟在 $fail 颜色 tag 之后"

    def test_active_failed_tab_uses_active_markup_not_fail(self):
        tabs = [
            {"run_id": "r1", "goal": "active fail", "state": "failed", "cost_usd": 0.01},
        ]
        rendered = _render(tabs, active="r1")
        assert "#ECEEF5" in rendered and "#23263A" in rendered,\
            "活跃 tab 应使用 $ink-bright on $raise-2 底色块"
        assert f"[{_COL_FAIL}]" not in rendered,\
            "活跃 tab 不应单独给 ◉ 染 $fail(整段已用活跃色覆盖)"

    def test_non_active_running_tab_no_fail_color(self):
        tabs = [
            {"run_id": "r1", "goal": "running task", "state": "running", "cost_usd": 0.01},
        ]
        rendered = _render(tabs, active=None)
        assert _COL_FAIL not in rendered

    def test_non_active_completed_tab_no_fail_color(self):
        tabs = [
            {"run_id": "r1", "goal": "done task", "state": "completed", "cost_usd": 0.03},
        ]
        rendered = _render(tabs, active=None)
        assert _COL_FAIL not in rendered

    def test_multiple_tabs_only_failed_colored(self):
        tabs = [
            {"run_id": "r1", "goal": "running", "state": "running", "cost_usd": 0.01},
            {"run_id": "r2", "goal": "failed run", "state": "failed", "cost_usd": 0.05},
            {"run_id": "r3", "goal": "done", "state": "completed", "cost_usd": 0.02},
        ]
        rendered = _render(tabs, active="r1")
        assert _COL_FAIL in rendered, "failed tab 应含 $fail 颜色"
        fail_tag_count = rendered.count(f"[{_COL_FAIL}]")
        assert fail_tag_count == 1,\
            f"期望恰好 1 个 $fail 开始 tag(对应 1 个 failed tab),实际 {fail_tag_count}"


# ─────────────────────────────────────────────────────────────────────────────
# ─────────────────────────────────────────────────────────────────────────────

class TestGlyphDictionary:
    def test_failed_maps_to_fisheye(self):
        assert _STATE_ICON["failed"] == "◉"

    def test_blocked_glyph_not_in_state_icon(self):
        assert "◓" not in _STATE_ICON.values(),\
            "◓ 是 blocked-only 保留字形,不得出现在 TabStrip._STATE_ICON"

    def test_completed_maps_to_dot_right_half(self):
        assert _STATE_ICON["completed"] == "◕"

    def test_pending_maps_to_circle(self):
        assert _STATE_ICON["pending"] == "◌"

    def test_col_fail_constant_matches_theme(self):
        assert _COL_FAIL == "#F7768E"


# ─────────────────────────────────────────────────────────────────────────────
# ─────────────────────────────────────────────────────────────────────────────

class TestRenderBasics:
    def test_empty_tabs(self):
        rendered = _render([])
        assert rendered == "(no runs)"

    def test_active_tab_uses_raise2_bg(self):
        tabs = [{"run_id": "r1", "goal": "hello", "state": "running", "cost_usd": 0.01}]
        rendered = _render(tabs, active="r1")
        assert "#23263A" in rendered   # $raise-2

    def test_active_tab_uses_ink_bright(self):
        tabs = [{"run_id": "r1", "goal": "hello", "state": "running", "cost_usd": 0.01}]
        rendered = _render(tabs, active="r1")
        assert "#ECEEF5" in rendered   # $ink-bright

    def test_title_truncated_to_24(self):
        long_goal = "a" * 30
        tabs = [{"run_id": "r1", "goal": long_goal, "state": "running", "cost_usd": None}]
        rendered = _render(tabs, active=None)
        assert long_goal not in rendered
        assert "…" in rendered

    def test_cost_na_for_none(self):
        tabs = [{"run_id": "r1", "goal": "t", "state": "running", "cost_usd": None}]
        rendered = _render(tabs, active=None)
        assert "$N/A" in rendered


# ─────────────────────────────────────────────────────────────────────────────
# _format_cost
# ─────────────────────────────────────────────────────────────────────────────

class TestFormatCost:
    def test_none(self):
        assert _format_cost(None) == "$N/A"

    def test_sub_cent(self):
        assert _format_cost(0.005) == "$<0.01"

    def test_sub_dollar(self):
        assert _format_cost(0.5) == "$0.500"

    def test_over_dollar(self):
        assert _format_cost(1.23) == "$1.23"


# ─────────────────────────────────────────────────────────────────────────────
# finding #33: CJK-safe truncation (cell width, not len)
# ─────────────────────────────────────────────────────────────────────────────

class TestCjkTruncation:

    def test_ascii_truncation_unchanged(self):
        assert _truncate("hello", 10) == "hello"
        result = _truncate("a" * 30, 24)
        assert result.endswith("…")
        assert _cell_len(result) <= 24

    def test_cjk_title_truncates_by_cell_width(self):
        title = "这是一个很长的中文任务名称标题"
        result = _truncate(title, 24)
        assert result.endswith("…"), f"CJK 截断结果须以 … 结尾: {result!r}"
        assert _cell_len(result) <= 24, (
            f"截断后 cell_len={_cell_len(result)} 超过 24: {result!r}"
        )

    def test_cjk_short_title_not_truncated(self):
        title = "短任务"
        assert _truncate(title, 24) == title

    def test_mixed_cjk_ascii_truncation(self):
        title = "Task-任务执行-2026"
        result = _truncate(title, 24)
        assert _cell_len(result) <= 24

    def test_update_tabs_truncates_cjk_correctly(self):
        strip = TabStrip()
        long_cjk = "中" * 15
        strip.update_tabs([{
            "run_id": "r1", "goal": long_cjk,
            "state": "running", "cost_usd": None,
        }])
        tab = strip.get_tabs()[0]
        assert _cell_len(tab["title"]) <= 24, (
            f"tab 标题 cell_len={_cell_len(tab['title'])} 超过 24"
        )
        assert tab["title"].endswith("…")


# ─────────────────────────────────────────────────────────────────────────────
# finding #26: CJK-safe click hit-test
# ─────────────────────────────────────────────────────────────────────────────

class TestCjkClickHitTest:

    def test_cell_len_imported(self):
        assert callable(_cell_len)

    def test_cjk_title_cell_len_is_double_ascii(self):
        title = "任务"
        assert _cell_len(title) == 4
        assert len(title) == 2

    def test_truncate_uses_cell_len_for_cjk(self):
        title = "中" * 12
        result = _truncate(title, 24)
        assert result == title
        title_overflow = "中" * 13
        result2 = _truncate(title_overflow, 24)
        assert _cell_len(result2) <= 24
        assert result2.endswith("…")
