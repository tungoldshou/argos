# tests/test_code_action_block.py
import pytest
from textual.app import App, ComposeResult
from argos.tui.theme import ARGOS_NIGHT
from argos.tui.widgets.code_action import CodeActionBlock


class _H(App):
    """最小测试宿主：注入 argos-night token 以便 DEFAULT_CSS 中 $token 在 CSS 解析阶段可用。

    get_theme_variable_defaults() 在 DEFAULT_CSS 首次解析前运行，
    是让自定义 $token 在测试环境中可用的唯一手段。
    """

    def get_theme_variable_defaults(self) -> dict[str, str]:
        """把 ARGOS_NIGHT.variables 作为 CSS token 兜底注入。"""
        defaults = super().get_theme_variable_defaults()
        if ARGOS_NIGHT.variables:
            defaults.update(ARGOS_NIGHT.variables)
        return defaults

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
        # TUI v2 扁平块:⏺ 字形 + step 在 #header Static(无边框盒,无 border_title)
        header = str(app.block.query_one("#header").render())
        assert "⏺" in header
        assert "2" in header
        assert "┌" not in header


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
