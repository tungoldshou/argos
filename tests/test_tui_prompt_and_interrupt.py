"""多行输入框 PromptArea + slash 菜单 + Esc 打断 的回归测试。

作用域诚实:Pilot 是 headless,press() 把合成 Key 直接送进聚焦 widget,绕过 driver 的真实
输入管线(Kitty/legacy 解析)。这些测试证明的是 **handler 逻辑**(Enter→提交、反斜杠续行、
Tab 补全、/ 弹菜单、Esc 取消 run)正确,不证明真终端转义序列解码——那层由
test_kitty_keyboard_protocol_disabled_by_default 这类进程级断言守。
"""
from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

import pytest

from argos_agent.tui.app import ArgosApp
from argos_agent.tui.commands import match_commands
from argos_agent.tui.events import Event, PhaseChange
from argos_agent.tui.fakeloop import FakeLoop
from argos_agent.tui.widgets.prompt import PromptArea, SlashMenu


# ── match_commands 纯逻辑(slash 菜单 / Tab 补全的单一判据) ───────────────────
def test_match_commands_prefix_and_param_gate():
    assert [n for n, _ in match_commands("/he")] == ["help"]
    assert "model" in [n for n, _ in match_commands("/m")]
    assert match_commands("/") != []          # 单个 / 列全部
    assert match_commands("/model x") == []    # 已带参数不再提示
    assert match_commands("hello") == []       # 非 slash
    assert match_commands("") == []


# ── 多行输入 + 反斜杠续行 + 提交 ───────────────────────────────────────────────
@pytest.mark.asyncio
async def test_enter_submits_and_clears():
    app = ArgosApp(loop_factory=lambda: FakeLoop())
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
    app = ArgosApp(loop_factory=lambda: FakeLoop())
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        prompt = app.query_one("#prompt", PromptArea)
        await pilot.press("a")
        await pilot.press("backslash")   # 行尾反斜杠
        await pilot.press("enter")       # → 续行,不提交
        await pilot.pause()
        assert prompt.text == "a\n", "反斜杠+回车应换行而非提交"
        await pilot.press("b")
        assert prompt.text == "a\nb", "续行后可继续多行输入"


# ── slash 菜单显隐 + Tab 补全 ─────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_slash_menu_shows_and_tab_completes():
    app = ArgosApp(loop_factory=lambda: FakeLoop())
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
    """TUI v2 §6.1:菜单可见时 ↑↓ 移动 ▸ 选中项,Enter 执行选中命令(不再只能首项)。"""
    app = ArgosApp(loop_factory=lambda: FakeLoop())
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
        await pilot.press("enter")     # 执行选中(第二项 = tools)
        await pilot.pause()
        log = app.query_one("#transcript")
        assert "工具" in log.rendered_text or second in log.rendered_text
        assert menu.display is False


@pytest.mark.asyncio
async def test_slash_menu_tab_completes_arrow_selected():
    """↓ 改选后 Tab 补全的是选中项,不是首项。"""
    app = ArgosApp(loop_factory=lambda: FakeLoop())
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
    app = ArgosApp(loop_factory=lambda: FakeLoop())
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        menu = app.query_one("#slash-menu", SlashMenu)
        for c in "abc":
            await pilot.press(c)
        await pilot.pause()
        assert menu.display is False, "普通目标输入不应弹命令菜单"


# ── Esc 打断当前 run ──────────────────────────────────────────────────────────
class _SlowLoop:
    """先发一个 PhaseChange,再长睡(可被取消)—— 模拟"模型推理中"的可中断 await 点。"""

    async def run(self, goal: str, session_id: str) -> AsyncIterator[Event]:
        yield PhaseChange(phase="plan", actions=0)
        await asyncio.sleep(60)   # 卡在这里,等 Esc 取消
        yield PhaseChange(phase="report", actions=1)


@pytest.mark.asyncio
async def test_escape_interrupts_active_run():
    app = ArgosApp(loop_factory=lambda: _SlowLoop(), demo=False)
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        app.handle_input("做一件事")          # 起一轮 run(worker)
        await pilot.pause()
        await pilot.pause()
        assert app._run_active is True, "run 应正在进行"
        await pilot.press("escape")           # 打断
        await pilot.pause()
        await pilot.pause()
        assert app._run_active is False, "Esc 后 run 应结束"
        log = app.query_one("#transcript")
        assert "已打断" in log.rendered_text, "应落一行明确的打断提示"


@pytest.mark.asyncio
async def test_escape_when_idle_is_noop():
    app = ArgosApp(loop_factory=lambda: FakeLoop())
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        await pilot.press("escape")   # 无 run、无菜单 → 不崩、不报错
        await pilot.pause()
        assert app.is_running


@pytest.mark.asyncio
async def test_escape_closes_slash_menu_before_interrupting():
    app = ArgosApp(loop_factory=lambda: FakeLoop())
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        menu = app.query_one("#slash-menu", SlashMenu)
        await pilot.press("/")
        await pilot.pause()
        assert menu.display is True
        await pilot.press("escape")
        await pilot.pause()
        assert menu.display is False, "Esc 应先收起 slash 菜单(不打断)"
