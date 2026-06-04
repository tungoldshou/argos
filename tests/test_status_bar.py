# tests/test_status_bar.py
import pytest
from textual.app import App, ComposeResult
from argos_agent.tui.widgets.status_bar import StatusBar


class _H(App):
    def compose(self) -> ComposeResult:
        yield StatusBar(id="sb")


@pytest.mark.asyncio
async def test_status_bar_shows_phase_actions_elapsed():
    app = _H()
    async with app.run_test() as pilot:
        await pilot.pause()
        sb = app.query_one("#sb", StatusBar)
        sb.set_phase("verify", 3)
        sb.set_cost(tokens_in=1, tokens_out=2, cost_usd=0.0, elapsed_s=4.2)
        await pilot.pause()
        t = sb.render_text
        assert "verify" in t and "3" in t and "4.2" in t
