# tests/test_thinking_indicator.py
import pytest
from textual.app import App, ComposeResult
from argos_agent.tui.widgets.thinking import ThinkingIndicator


class _H(App):
    def compose(self) -> ComposeResult:
        yield ThinkingIndicator(id="th")


@pytest.mark.asyncio
async def test_spinner_cycles_glyph():
    app = _H()
    async with app.run_test() as pilot:
        await pilot.pause()
        th = app.query_one("#th", ThinkingIndicator)
        first = th._frame
        th._tick()
        assert th._frame != first, "tick 应推进 spinner 帧"
        assert th.renderable  # 有内容
