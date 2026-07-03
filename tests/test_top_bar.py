"""Internal documentation."""
from __future__ import annotations

import pytest
from textual.app import App, ComposeResult

from argos.tui.widgets.top_bar import TopBar


class _H(App):
    def compose(self) -> ComposeResult:
        yield TopBar(version="1.2.3", model_label="MiniMax-M3", id="tb")


@pytest.mark.asyncio
async def test_topbar_shows_brand_version_model():
    """Internal documentation."""
    app = _H()
    async with app.run_test() as pilot:
        await pilot.pause()
        tb = app.query_one("#tb", TopBar)
        t = tb.render_text
        assert "Argos" in t and "1.2.3" in t and "MiniMax-M3" in t


@pytest.mark.asyncio
async def test_topbar_shows_unsandboxed_badge_when_off(monkeypatch):
    """Internal documentation."""
    monkeypatch.setenv("ARGOS_SANDBOX", "0")
    app = _H()
    async with app.run_test() as pilot:
        await pilot.pause()
        tb = app.query_one("#tb", TopBar)
        assert "未沙箱化" in tb.render_text


@pytest.mark.asyncio
async def test_topbar_no_unsandboxed_badge_when_on(monkeypatch):
    """Internal documentation."""
    monkeypatch.setenv("ARGOS_SANDBOX", "1")
    app = _H()
    async with app.run_test() as pilot:
        await pilot.pause()
        tb = app.query_one("#tb", TopBar)
        assert "未沙箱化" not in tb.render_text


@pytest.mark.asyncio
async def test_topbar_logo_eye_glyph_not_star():
    """Internal documentation."""
    app = _H()
    async with app.run_test() as pilot:
        await pilot.pause()
        tb = app.query_one("#tb", TopBar)
        t = tb.render_text
        assert "✳" not in t, f"v3 不应出现旧品牌符 ✳,实际: {t!r}"
        assert "◌" in t, f"idle 态应显 ◌ 空态眼,实际: {t!r}"


@pytest.mark.asyncio
async def test_topbar_phase_eye_changes():
    """Internal documentation."""
    app = _H()
    async with app.run_test() as pilot:
        await pilot.pause()
        tb = app.query_one("#tb", TopBar)

        tb.set_phase("act")
        assert "◉" in tb.render_text, "act 阶段应显注视眼 ◉"

        tb.set_phase("verify")
        assert "❂" in tb.render_text, "verify 阶段应显聚焦眼 ❂"

        tb.set_phase("report")
        assert "◕" in tb.render_text, "report 阶段应显阅毕眼 ◕"

        tb.set_phase("plan")
        assert "◔" in tb.render_text, "plan 阶段应显扫视眼 ◔"

        tb.set_phase("idle")
        assert "◌" in tb.render_text, "idle 阶段应显空态眼 ◌"


@pytest.mark.asyncio
async def test_topbar_no_key_badge_never_lies_live():
    """Internal documentation."""
    app = _H()
    async with app.run_test() as pilot:
        await pilot.pause()
        tb = app.query_one("#tb", TopBar)
        tb.set_state(has_key=False)
        assert "LIVE" not in tb.render_text, (
            f"无 key 时 render_text 绝不含 LIVE,实际: {tb.render_text!r}"
        )
        assert any("未配 key" in b for b in tb.badges())


@pytest.mark.asyncio
async def test_topbar_live_badge_present_with_key():
    """Internal documentation."""
    app = _H()
    async with app.run_test() as pilot:
        await pilot.pause()
        tb = app.query_one("#tb", TopBar)
        tb.set_state(has_key=True)
        assert any("LIVE" in b for b in tb.badges()), (
            f"有 key 时 badges 应含 LIVE,实际: {tb.badges()!r}"
        )


@pytest.mark.asyncio
async def test_topbar_plan_and_yolo_badges():
    """Internal documentation."""
    app = _H()
    async with app.run_test() as pilot:
        await pilot.pause()
        tb = app.query_one("#tb", TopBar)
        tb.set_state(plan_mode=True, yolo=True)
        bs = tb.badges()
        assert any("plan" in b for b in bs), f"plan_mode 应有 plan 徽标,实际: {bs!r}"
        assert any("YOLO" in b for b in bs), f"yolo 应有 YOLO 徽标,实际: {bs!r}"
        assert "[plan mode]" not in bs, "v3 不应再出现 [plan mode] 方括号格式"
        tb.set_state(plan_mode=False, yolo=False)
        bs = tb.badges()
        assert not any("plan" in b and b == "plan" for b in bs)
        assert not any("YOLO" in b for b in bs)


@pytest.mark.asyncio
async def test_topbar_no_bullet_before_live():
    """Internal documentation."""
    app = _H()
    async with app.run_test() as pilot:
        await pilot.pause()
        tb = app.query_one("#tb", TopBar)
        tb.set_state(has_key=True)
        t = tb.render_text
        assert "●" not in t, f"v3 ● 被处决,不应出现在渲染文本中,实际: {t!r}"
