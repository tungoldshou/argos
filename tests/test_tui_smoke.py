"""Phase 1 冒烟:Textual App 能起来且占位 widget 可见。"""
import pytest

from argos_agent.tui.app import ArgosApp


@pytest.mark.asyncio
async def test_app_boots_and_shows_welcome():
    app = ArgosApp()
    async with app.run_test() as pilot:
        await pilot.pause()
        welcome = app.query_one("#welcome")
        assert "骨架" in str(welcome.render())
        assert "Argos" in app.title
