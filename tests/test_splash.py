import pytest
from argos_agent.tui.app import ArgosApp
from argos_agent.tui.fakeloop import FakeLoop
from argos_agent.tui.widgets.splash import StartupSplash


@pytest.mark.asyncio
async def test_splash_shown_on_mount_with_mode_badge():
    app = ArgosApp(loop_factory=lambda: FakeLoop())   # demo 默认 True
    async with app.run_test() as pilot:
        await pilot.pause()
        sp = list(app.query(StartupSplash))
        assert len(sp) == 1
        assert "ARGOS" in sp[0].renderable_text
        assert "DEMO" in sp[0].renderable_text          # demo 模式诚实徽标


@pytest.mark.asyncio
async def test_splash_cleared_on_first_run():
    app = ArgosApp(loop_factory=lambda: FakeLoop())
    async with app.run_test() as pilot:
        await pilot.pause()
        await app.start_run("演示任务")
        await app.workers.wait_for_complete()
        await pilot.pause()
        assert len(list(app.query(StartupSplash))) == 0, "起一轮后 splash 应被清除"
