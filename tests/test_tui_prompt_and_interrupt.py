from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

import pytest

from argos.tui.app import ArgosApp
from argos.tui.commands import match_commands
from argos.tui.events import Event, PhaseChange
from argos.tui.fakeloop import FakeLoop
from argos.tui.widgets.prompt import PromptArea, SlashMenu


def test_match_commands_prefix_and_param_gate():
    assert [n for n, _ in match_commands("/he")] == ["help"]
    assert "model" in [n for n, _ in match_commands("/m")]
    assert match_commands("/") != []
    assert match_commands("/model x") == []
    assert match_commands("hello") == []
    assert match_commands("") == []


@pytest.mark.asyncio
async def test_enter_submits_and_clears():
    app = ArgosApp(loop_factory=lambda **kw: FakeLoop())
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        prompt = app.query_one("#prompt", PromptArea)
        for c in "hi":
            await pilot.press(c)
        await pilot.press("enter")
        await pilot.pause()
        assert prompt.text == "", "Enter 提交后输入框应清空"


@pytest.mark.asyncio
async def test_backslash_continuation_inserts_newline_not_submit():
    app = ArgosApp(loop_factory=lambda **kw: FakeLoop())
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        prompt = app.query_one("#prompt", PromptArea)
        await pilot.press("a")
        await pilot.press("backslash")
        await pilot.press("enter")
        await pilot.pause()
        assert prompt.text == "a\n", "反斜杠+回车应换行而非提交"
        await pilot.press("b")
        assert prompt.text == "a\nb", "续行后可继续多行输入"


@pytest.mark.asyncio
async def test_slash_menu_shows_and_tab_completes():
    app = ArgosApp(loop_factory=lambda **kw: FakeLoop())
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        prompt = app.query_one("#prompt", PromptArea)
        menu = app.query_one("#slash-menu", SlashMenu)
        assert menu.display is False, "初始 slash 菜单应隐藏"
        await pilot.press("/")
        await pilot.pause()
        assert menu.display is True, "打 / 应弹出命令菜单"
        for c in "he":
            await pilot.press(c)
        await pilot.pause()
        assert menu.display is True and prompt.text == "/he"
        await pilot.press("tab")
        await pilot.pause()
        assert prompt.text == "/help ", "Tab 应补全到首个匹配命令"
        assert menu.display is False, "补全带参后菜单应隐藏"


@pytest.mark.asyncio
async def test_slash_menu_arrow_selects_and_enter_runs_selected():
    app = ArgosApp(loop_factory=lambda **kw: FakeLoop())
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        menu = app.query_one("#slash-menu", SlashMenu)
        await pilot.press("/")
        await pilot.pause()
        assert menu.display is True
        first = menu.selected()
        await pilot.press("down")
        await pilot.pause()
        second = menu.selected()
        assert first is not None and second is not None and second != first
        await pilot.press("enter")
        await pilot.pause()
        log = app.query_one("#transcript")
        assert (
            "工具" in log.rendered_text
            or second in log.rendered_text
            or (second == "setup" and "active profile" in log.rendered_text)
        )
        assert menu.display is False


@pytest.mark.asyncio
async def test_slash_menu_tab_completes_arrow_selected():
    app = ArgosApp(loop_factory=lambda **kw: FakeLoop())
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        prompt = app.query_one("#prompt", PromptArea)
        menu = app.query_one("#slash-menu", SlashMenu)
        await pilot.press("/")
        await pilot.pause()
        await pilot.press("down")
        await pilot.pause()
        sel = menu.selected()
        await pilot.press("tab")
        await pilot.pause()
        assert prompt.text == f"/{sel} "


@pytest.mark.asyncio
async def test_slash_menu_hides_for_non_slash():
    app = ArgosApp(loop_factory=lambda **kw: FakeLoop())
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        menu = app.query_one("#slash-menu", SlashMenu)
        for c in "abc":
            await pilot.press(c)
        await pilot.pause()
        assert menu.display is False, "普通目标输入不应弹命令菜单"


class _SlowLoop:

    async def run(self, goal: str, session_id: str) -> AsyncIterator[Event]:
        yield PhaseChange(phase="plan", actions=0)
        await asyncio.sleep(60)
        yield PhaseChange(phase="report", actions=1)


@pytest.mark.asyncio
async def test_escape_interrupts_active_run():
    app = ArgosApp(loop_factory=lambda **kw: _SlowLoop())
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        app.handle_input("做一件事")
        await pilot.pause()
        await pilot.pause()
        assert app._run_active is True, "run 应正在进行"
        await pilot.press("escape")
        await pilot.pause()
        await pilot.pause()
        assert app._run_active is False, "Esc 后 run 应结束"
        log = app.query_one("#transcript")
        assert "已打断" in log.rendered_text, "应落一行明确的打断提示"


@pytest.mark.asyncio
async def test_escape_when_idle_is_noop():
    app = ArgosApp(loop_factory=lambda **kw: FakeLoop())
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        await pilot.press("escape")
        await pilot.pause()
        assert app.is_running


@pytest.mark.asyncio
async def test_escape_closes_slash_menu_before_interrupting():
    app = ArgosApp(loop_factory=lambda **kw: FakeLoop())
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        menu = app.query_one("#slash-menu", SlashMenu)
        await pilot.press("/")
        await pilot.pause()
        assert menu.display is True
        await pilot.press("escape")
        await pilot.pause()
        assert menu.display is False, "Esc 应先收起 slash 菜单(不打断)"
