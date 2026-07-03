from __future__ import annotations

import pytest

from argos.tui.app import ArgosApp
from argos.tui.events import CodeAction, CodeResult
from argos.tui.fakeloop import FakeLoop
from argos.tui.widgets.code_action import CodeActionBlock
from argos.tui.widgets.transcript import SystemLine, Transcript, UserMessage

_BRACKETY = "已点击 \"input[value='Google Search']\" [返回值] [1, 2, 3] list[str] [/not a tag]"


def test_static_widgets_constructed_markup_false():
    assert UserMessage(_BRACKETY)._render_markup is False
    assert SystemLine(_BRACKETY)._render_markup is False
    assert CodeActionBlock(code="x=1", step=0) is not None


@pytest.mark.asyncio
async def test_code_result_with_brackets_does_not_crash():
    app = ArgosApp(loop_factory=lambda **kw: FakeLoop())
    async with app.run_test() as pilot:
        await pilot.pause()
        await app._apply_event(CodeAction(code="print(browser_click('input'))", step=0))
        await app._apply_event(CodeResult(step=0, stdout=_BRACKETY, value_repr=_BRACKETY,
                                          exc="", ok=True))
        await pilot.pause()
        assert app.is_running
        blocks = list(app.query(CodeActionBlock))
        assert blocks and blocks[0].ok is True
        result = blocks[0].query_one("#result")
        assert "input[value=" in str(result.render())


@pytest.mark.asyncio
async def test_user_and_system_lines_with_brackets_render():
    app = ArgosApp(loop_factory=lambda **kw: FakeLoop())
    async with app.run_test() as pilot:
        await pilot.pause()
        log = app.query_one("#transcript", Transcript)
        await log.user_line("修个 bug:list[int] 和 dict[str, int]")
        await log.append_line(f"工具输出:{_BRACKETY}", kind="error")
        await pilot.pause()
        assert app.is_running
        assert "list[int]" in log.rendered_text
