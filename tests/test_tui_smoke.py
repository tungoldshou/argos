"""Phase 1 冒烟:Textual App 能起来(Phase 5 起已无 #welcome 骨架占位,改验主布局)。"""
import pytest

from argos.tui.app import ArgosApp
from argos.tui.widgets.status_bar import StatusBar
from argos.tui.widgets.transcript import Transcript


@pytest.mark.asyncio
async def test_app_boots_with_main_layout():
    app = ArgosApp()
    async with app.run_test() as pilot:
        await pilot.pause()
        # Phase 5 起骨架占位已换成真实 layout
        assert app.query_one("#transcript", Transcript) is not None
        assert app.query_one("#status-bar", StatusBar) is not None
        assert "Argos" in app.title
