import pytest
from textual.app import App, ComposeResult
from argos_agent.tui.widgets.verdict_badge import VerdictBadge
from argos_agent.core.verify_gate import Verdict


class _H(App):
    def compose(self) -> ComposeResult:
        yield VerdictBadge(id="vb")


@pytest.mark.asyncio
async def test_three_states_get_distinct_classes():
    app = _H()
    async with app.run_test() as pilot:
        await pilot.pause()
        vb = app.query_one("#vb", VerdictBadge)
        vb.show(Verdict.passed(detail="ok", verify_cmd="echo", attempts=1))
        await pilot.pause()
        assert vb.has_class("verdict-passed")
        vb.show(Verdict.failed(detail="bad", verify_cmd="echo", attempts=1))
        await pilot.pause()
        assert vb.has_class("verdict-failed") and not vb.has_class("verdict-passed")
        vb.show(Verdict.unverifiable(detail="??", tampered=[], attempts=1))
        await pilot.pause()
        assert vb.has_class("verdict-unverifiable") and not vb.has_class("verdict-failed")
