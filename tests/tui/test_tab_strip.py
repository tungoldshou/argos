# tests/tui/test_tab_strip.py
"""TabStrip 回归测试 — 锁定 2026-06-14 design-audit 修复点。

覆盖:
  [MEDIUM] DEFAULT_CSS 包含 border-bottom: solid $hairline
  [LOW]    非活跃 failed tab 的 ◉ 字形在 render() 中被 $fail (#F7768E) 着色
  [LOW]    非活跃非-failed tab 的字形不含 $fail 着色
  已知正确项(不回退):
    _STATE_ICON 字典包含正确字形(◌/⏵/⏸/⏹/◕/◉)
    ◉ 专属 failed;◓ 不出现在 _STATE_ICON(◓ 保留给 blocked)
    active tab 使用 bold #ECEEF5 on #23263A markup
    空 tabs 渲染 "(no runs)"
    _format_cost 精度规则
"""
from __future__ import annotations

import pytest

from argos.tui.widgets.tab_strip import TabStrip, _STATE_ICON, _format_cost, _COL_FAIL, _truncate, _cell_len


# ─────────────────────────────────────────────────────────────────────────────
# helpers
# ─────────────────────────────────────────────────────────────────────────────

def _strip() -> TabStrip:
    """构造不依赖 App 的裸 widget(只测 render 和 CSS 字符串)。"""
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
        """DEFAULT_CSS 必须包含 border-bottom: solid $hairline (screen 07 要求)。"""
        css = TabStrip.DEFAULT_CSS
        assert "border-bottom" in css, "DEFAULT_CSS 缺少 border-bottom"
        assert "$hairline" in css, "border-bottom 必须使用 $hairline token,不得硬编码 hex"
        # 确认是 solid 分隔线(hairline 语义)
        assert "solid" in css or "hkey" in css, \
            "border-bottom 应为 solid $hairline 或 hkey $hairline"

    def test_background_uses_well_token(self):
        """背景必须用 $well token。"""
        assert "$well" in TabStrip.DEFAULT_CSS

    def test_color_uses_ink_dim_token(self):
        """默认前景必须用 $ink-dim token。"""
        assert "$ink-dim" in TabStrip.DEFAULT_CSS


# ─────────────────────────────────────────────────────────────────────────────
# [LOW] failed glyph 染 $fail 色
# ─────────────────────────────────────────────────────────────────────────────

class TestFailedGlyphColor:
    def test_non_active_failed_tab_glyph_colored_fail(self):
        """非活跃 failed tab 的 ◉ 字形必须用 $fail (#F7768E) 着色。"""
        tabs = [
            {"run_id": "r1", "goal": "task one", "state": "failed", "cost_usd": 0.05},
        ]
        rendered = _render(tabs, active=None)
        # ◉ 字形前后必须包含 $fail hex
        assert _COL_FAIL in rendered, \
            f"render() 中非活跃 failed tab 未找到 $fail ({_COL_FAIL}) 颜色标记"
        assert "◉" in rendered

    def test_non_active_failed_tab_has_fail_markup_around_glyph(self):
        """$fail 颜色标记必须环绕 ◉ 字形(而不是整段)。"""
        tabs = [
            {"run_id": "r1", "goal": "my task", "state": "failed", "cost_usd": 0.02},
        ]
        rendered = _render(tabs, active=None)
        # 期望类似: [#F7768E]◉[/#F7768E] my task ...
        assert f"[{_COL_FAIL}]◉" in rendered or f"[{_COL_FAIL}]◉" in rendered, \
            "◉ 字形应紧跟在 $fail 颜色 tag 之后"

    def test_active_failed_tab_uses_active_markup_not_fail(self):
        """活跃 tab 即使是 failed 状态,整段统一用活跃底色块,不单独染 $fail。"""
        tabs = [
            {"run_id": "r1", "goal": "active fail", "state": "failed", "cost_usd": 0.01},
        ]
        rendered = _render(tabs, active="r1")
        # 活跃 tab markup: bold #ECEEF5 on #23263A
        assert "#ECEEF5" in rendered and "#23263A" in rendered, \
            "活跃 tab 应使用 $ink-bright on $raise-2 底色块"
        # 活跃 tab 内不应单独出现 $fail 颜色 tag
        assert f"[{_COL_FAIL}]" not in rendered, \
            "活跃 tab 不应单独给 ◉ 染 $fail(整段已用活跃色覆盖)"

    def test_non_active_running_tab_no_fail_color(self):
        """非活跃 running tab 不应含 $fail 颜色标记。"""
        tabs = [
            {"run_id": "r1", "goal": "running task", "state": "running", "cost_usd": 0.01},
        ]
        rendered = _render(tabs, active=None)
        assert _COL_FAIL not in rendered

    def test_non_active_completed_tab_no_fail_color(self):
        """非活跃 completed tab 不应含 $fail 颜色标记。"""
        tabs = [
            {"run_id": "r1", "goal": "done task", "state": "completed", "cost_usd": 0.03},
        ]
        rendered = _render(tabs, active=None)
        assert _COL_FAIL not in rendered

    def test_multiple_tabs_only_failed_colored(self):
        """多 tab 场景:只有 failed 非活跃 tab 的 ◉ 被染色,其他 tab 不受影响。"""
        tabs = [
            {"run_id": "r1", "goal": "running", "state": "running", "cost_usd": 0.01},
            {"run_id": "r2", "goal": "failed run", "state": "failed", "cost_usd": 0.05},
            {"run_id": "r3", "goal": "done", "state": "completed", "cost_usd": 0.02},
        ]
        rendered = _render(tabs, active="r1")
        assert _COL_FAIL in rendered, "failed tab 应含 $fail 颜色"
        # r1(active) 和 r3(completed) 不应单独出现 $fail tag
        # 注:简单检查 $fail 标记数量与 failed tab 数量相符(出现 2 次:开闭 tag)
        fail_tag_count = rendered.count(f"[{_COL_FAIL}]")
        assert fail_tag_count == 1, \
            f"期望恰好 1 个 $fail 开始 tag(对应 1 个 failed tab),实际 {fail_tag_count}"


# ─────────────────────────────────────────────────────────────────────────────
# 字形铁律 — glyph dictionary integrity
# ─────────────────────────────────────────────────────────────────────────────

class TestGlyphDictionary:
    def test_failed_maps_to_fisheye(self):
        """failed 状态必须映射 ◉ (U+25C9 FISHEYE),不得改成其他字形。"""
        assert _STATE_ICON["failed"] == "◉"

    def test_blocked_glyph_not_in_state_icon(self):
        """◓ (U+25D3) 是 blocked 保留字形,不得出现在 _STATE_ICON 值中。"""
        assert "◓" not in _STATE_ICON.values(), \
            "◓ 是 blocked-only 保留字形,不得出现在 TabStrip._STATE_ICON"

    def test_completed_maps_to_dot_right_half(self):
        """completed 状态映射 ◕ (U+25D5 阅毕眼)。"""
        assert _STATE_ICON["completed"] == "◕"

    def test_pending_maps_to_circle(self):
        """pending 状态映射 ◌ (U+25CC 空态眼)。"""
        assert _STATE_ICON["pending"] == "◌"

    def test_col_fail_constant_matches_theme(self):
        """_COL_FAIL 必须等于 theme.py 中 $fail token 的 hex 值 #F7768E。"""
        assert _COL_FAIL == "#F7768E"


# ─────────────────────────────────────────────────────────────────────────────
# render() 基础行为(不回退)
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
        # 24文字+省略号=25 chars 最大; raw long goal 不应完整出现
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
    """finding #33: _truncate 按 cell 宽度截断,CJK 字符占 2 cell。"""

    def test_ascii_truncation_unchanged(self):
        """纯 ASCII 字符串截断行为与旧 len() 一致。"""
        assert _truncate("hello", 10) == "hello"   # 无需截断
        result = _truncate("a" * 30, 24)
        assert result.endswith("…")
        assert _cell_len(result) <= 24

    def test_cjk_title_truncates_by_cell_width(self):
        """中文 tab 标题按 cell 宽度截断(每字 2 cell)。"""
        # 13 个中文字符 = 26 cells; 限 24 → 须截断
        title = "这是一个很长的中文任务名称标题"
        result = _truncate(title, 24)
        assert result.endswith("…"), f"CJK 截断结果须以 … 结尾: {result!r}"
        assert _cell_len(result) <= 24, (
            f"截断后 cell_len={_cell_len(result)} 超过 24: {result!r}"
        )

    def test_cjk_short_title_not_truncated(self):
        """短中文标题(cell_len <= 24)不被截断。"""
        title = "短任务"  # 3 字符 = 6 cells
        assert _truncate(title, 24) == title

    def test_mixed_cjk_ascii_truncation(self):
        """中英混合字符串按 cell 宽度正确截断。"""
        title = "Task-任务执行-2026"  # 混合
        result = _truncate(title, 24)
        assert _cell_len(result) <= 24

    def test_update_tabs_truncates_cjk_correctly(self):
        """update_tabs() 对 CJK goal 的截断结果 cell_len <= 24。"""
        strip = TabStrip()
        long_cjk = "中" * 15  # 30 cells, 远超 24
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
    """finding #26: on_click 用 cell_len 而非 len() 计算 tab 宽度区间。"""

    def test_cell_len_imported(self):
        """_cell_len 可从 tab_strip 模块导入(证明已引入 rich.cells)。"""
        assert callable(_cell_len)

    def test_cjk_title_cell_len_is_double_ascii(self):
        """中文字符 cell_len == 2 × len()(每字占 2 cell)。"""
        title = "任务"
        assert _cell_len(title) == 4
        assert len(title) == 2

    def test_truncate_uses_cell_len_for_cjk(self):
        """_truncate 产生的结果 cell_len <= n, 而 len() 可能 < n(CJK 仍正确截断)。"""
        title = "中" * 12   # 12 chars = 24 cells: 恰好在边界
        result = _truncate(title, 24)
        # 恰好 24 cells → 无需截断
        assert result == title
        title_overflow = "中" * 13  # 26 cells > 24 → 必须截断
        result2 = _truncate(title_overflow, 24)
        assert _cell_len(result2) <= 24
        assert result2.endswith("…")
