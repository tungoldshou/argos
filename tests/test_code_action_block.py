# tests/test_code_action_block.py
import pytest
from textual.app import App, ComposeResult
from argos_agent.tui.widgets.code_action import CodeActionBlock


class _H(App):
    def __init__(self):
        super().__init__()
        self.block = CodeActionBlock(code="write_file('a','b')", step=2)
    def compose(self) -> ComposeResult:
        yield self.block


@pytest.mark.asyncio
async def test_header_uses_glyph_not_ascii_box():
    app = _H()
    async with app.run_test() as pilot:
        await pilot.pause()
        # border_title 用 ⏺ 字形 + step,不再手画 ┌ code-action
        assert "⏺" in str(app.block.border_title)
        assert "2" in str(app.block.border_title)
        assert "┌" not in str(app.block.border_title)


@pytest.mark.asyncio
async def test_result_ok_and_fail_class():
    app = _H()
    async with app.run_test() as pilot:
        await pilot.pause()
        app.block.set_result(stdout="2 passed", value_repr="", exc="", ok=True)
        await pilot.pause()
        assert app.block.ok is True
        app.block.set_result(stdout="", value_repr="", exc="Boom", ok=False)
        await pilot.pause()
        assert app.block.ok is False
