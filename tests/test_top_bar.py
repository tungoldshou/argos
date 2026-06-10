"""TopBar(TUI v2 spec §1.1):自绘顶栏徽标诚实性 —— 全部来自真实状态。"""
from __future__ import annotations

import pytest
from textual.app import App, ComposeResult

from argos_agent.tui.widgets.top_bar import TopBar


class _H(App):
    def compose(self) -> ComposeResult:
        yield TopBar(version="1.2.3", model_label="MiniMax-M3", id="tb")


@pytest.mark.asyncio
async def test_topbar_shows_brand_version_model():
    app = _H()
    async with app.run_test() as pilot:
        await pilot.pause()
        tb = app.query_one("#tb", TopBar)
        t = tb.render_text
        assert "Argos" in t and "1.2.3" in t and "MiniMax-M3" in t


@pytest.mark.asyncio
async def test_topbar_demo_badge_honest():
    """默认 demo=True → DEMO 徽标常驻(诚实铁律:脚本演示绝不冒充真实执行)。"""
    app = _H()
    async with app.run_test() as pilot:
        await pilot.pause()
        tb = app.query_one("#tb", TopBar)
        assert any("DEMO" in b for b in tb.badges())
        # 切真 loop + 有 key → DEMO 消失,且不显 未配 key
        tb.set_state(demo=False, has_key=True)
        assert not any("DEMO" in b for b in tb.badges())
        assert not any("未配 key" in b for b in tb.badges())


@pytest.mark.asyncio
async def test_topbar_no_key_badge_never_lies_live():
    """live 但无 key → ⚠ 未配 key(绝不撒 LIVE 的谎)。"""
    app = _H()
    async with app.run_test() as pilot:
        await pilot.pause()
        tb = app.query_one("#tb", TopBar)
        tb.set_state(demo=False, has_key=False)
        assert any("未配 key" in b for b in tb.badges())


@pytest.mark.asyncio
async def test_topbar_plan_and_yolo_badges():
    app = _H()
    async with app.run_test() as pilot:
        await pilot.pause()
        tb = app.query_one("#tb", TopBar)
        tb.set_state(plan_mode=True, yolo=True)
        bs = tb.badges()
        assert "[plan mode]" in bs and "⏻ YOLO" in bs
        tb.set_state(plan_mode=False, yolo=False)
        bs = tb.badges()
        assert "[plan mode]" not in bs and "⏻ YOLO" not in bs
