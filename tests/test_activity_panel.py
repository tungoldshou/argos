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
        assert "未加载" in txt                                    # Skills 诚实空态
        assert "0" in txt                                        # MCP 0 已连接
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
