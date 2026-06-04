# tests/test_tui_theme.py
import pytest
from argos_agent.tui.app import ArgosApp
from argos_agent.tui.fakeloop import FakeLoop


@pytest.mark.asyncio
async def test_argos_night_theme_registered_and_applied():
    app = ArgosApp(loop_factory=lambda: FakeLoop())
    async with app.run_test() as pilot:
        await pilot.pause()
        assert app.theme == "argos-night", "应默认应用 argos-night 主题"
        assert "argos-night" in app.available_themes, "主题必须已注册"


@pytest.mark.asyncio
async def test_argos_night_tokens():
    from argos_agent.tui.theme import ARGOS_NIGHT
    assert ARGOS_NIGHT.dark is True
    # 唯一暖橙强调
    assert ARGOS_NIGHT.accent.lower() == "#e0af68"
    # 语义三色相分明(诚实:verdict 不能同色)
    assert ARGOS_NIGHT.success.lower() == "#9ece6a"
    assert ARGOS_NIGHT.error.lower() == "#f7768e"
