import pytest
from textual.app import App, ComposeResult
from argos_agent.tui.widgets.activity_panel import ActivityPanel
from argos_agent.core.types import ModelTierName  # noqa


class _H(App):
    def compose(self) -> ComposeResult:
        yield ActivityPanel(id="ap", model_label="MiniMax-M3", tier="worker")


@pytest.mark.asyncio
async def test_panel_sections_present_and_honest_empty():
    app = _H()
    async with app.run_test() as pilot:
        await pilot.pause()
        ap = app.query_one("#ap", ActivityPanel)
        txt = ap.snapshot_text()
        assert "MiniMax-M3" in txt                              # 模型(真,只显模型名不露档位)
        # Skills 已接进活 loop:诚实显真实可用数(内置 4 个)或"无可用",绝不谎报。
        assert ("可用" in txt or "无可用" in txt)
        # MCP 诚实显配置态:'未配置'(零预配)或 'N 个已配置';绝不谎报连接数。
        assert ("未配置" in txt or "已配置" in txt)
        assert "缓存" in txt                                      # 成本含缓存区


@pytest.mark.asyncio
async def test_phase_timeline_accumulates():
    app = _H()
    async with app.run_test() as pilot:
        await pilot.pause()
        ap = app.query_one("#ap", ActivityPanel)
        ap.on_phase("plan", 0)
        ap.on_phase("act", 1)
        await pilot.pause()
        assert "plan" in ap.snapshot_text() and "act" in ap.snapshot_text()


@pytest.mark.asyncio
async def test_receipt_and_cost_update():
    app = _H()
    async with app.run_test() as pilot:
        await pilot.pause()
        ap = app.query_one("#ap", ActivityPanel)
        ap.on_receipt("write_file")
        ap.on_cost(tokens_in=12400, tokens_out=3100, cost_usd=0.013, elapsed_s=4.2, cache_read=179)
        await pilot.pause()
        t = ap.snapshot_text()
        assert "write_file" in t           # 工具计数 + 回执
        assert "179" in t                  # 缓存命中


@pytest.mark.asyncio
async def test_model_section_shows_name_not_tier():
    app = _H()  # _H 已在该文件:yield ActivityPanel(id="ap", model_label="MiniMax-M3", tier="worker")
    async with app.run_test() as pilot:
        await pilot.pause()
        ap = app.query_one("#ap", ActivityPanel)
        txt = ap.snapshot_text()
        assert "MiniMax-M3" in txt, "应显示真实模型名"
        assert "档位" not in txt and "worker" not in txt, "不得暴露内部档位/tier 概念"


@pytest.mark.asyncio
async def test_cost_unknown_shows_na_not_zero():
    app = _H()
    async with app.run_test() as pilot:
        await pilot.pause()
        ap = app.query_one("#ap", ActivityPanel)
        ap.on_cost(tokens_in=100, tokens_out=50, cost_usd=None, elapsed_s=1.0, cache_read=0)
        await pilot.pause()
        t = ap.snapshot_text()
        assert "N/A" in t, "单价未知应显 $(N/A)"
        assert "$0.000" not in t


@pytest.mark.asyncio
async def test_context_section_shows_usage_bar():
    app = _H()
    async with app.run_test() as pilot:
        await pilot.pause()
        ap = app.query_one("#ap", ActivityPanel)
        ap.on_context(used=50000, window=200000)  # 25%
        await pilot.pause()
        t = ap.snapshot_text()
        assert "25%" in t
        assert "上下文" in t


@pytest.mark.asyncio
async def test_panel_is_scrollable():
    """修复:活动栏内容超出可视高度时必须可滚(overflow-y: auto);
    此前继承 Vertical 默认 overflow-y: hidden,区块被裁死、滚轮/拖拽全失效。"""
    app = _H()
    async with app.run_test() as pilot:
        await pilot.pause()
        ap = app.query_one("#ap", ActivityPanel)
        assert ap.styles.overflow_y == "auto", \
            f"活动栏应 overflow-y: auto 才能滚动,实际 {ap.styles.overflow_y}"


@pytest.mark.asyncio
async def test_section_title_not_transparent():
    """修复:区块标题此前 border-title-color 落到透明默认(alpha=0)完全看不见;
    须为不透明可读色($foreground)。"""
    app = _H()
    async with app.run_test() as pilot:
        await pilot.pause()
        ap = app.query_one("#ap", ActivityPanel)
        c = ap._sections()[0].styles.border_title_color
        assert c is not None and c.a > 0, f"区块标题颜色不得透明(alpha=0),实际 {c!r}"


@pytest.mark.asyncio
async def test_in_progress_phase_shows_ellipsis_not_zero():
    app = _H()
    async with app.run_test() as pilot:
        await pilot.pause()
        ap = app.query_one("#ap", ActivityPanel)
        ap.on_phase("plan", 0)  # 刚进 plan,进行中
        await pilot.pause()
        # Textual 8.2.7 的 Static 用 .content 暴露正文(无 .renderable)
        sec = str(ap._sections()[1].content)  # 任务进度区
        assert "0.0s" not in sec, "进行中阶段不应显 0.0s"
        assert "…" in sec, "进行中阶段应显占位 …"
