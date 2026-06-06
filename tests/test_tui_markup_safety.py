"""回归:任意工具/模型文本含 `[...]` 时,TUI 渲染绝不能崩(Rich markup 注入)。

真终端实测复现:让 agent 用浏览器搜索,工具返回 `已点击 "input[value='Google Search']"`,
`[value='...']` 被 Textual 当控制台 markup 标签解析 → MarkupError 直接崩掉整个 TUI。
根因:UserMessage/SystemLine/CodeActionBlock结果/活动栏/VerdictBadge/StatusBar 都是 Static,
默认 markup=True。修:全部 markup=False(任意文本按纯文本渲染)。本测试守住不回归。
"""
from __future__ import annotations

import pytest

from argos_agent.tui.app import ArgosApp
from argos_agent.tui.events import CodeAction, CodeResult
from argos_agent.tui.fakeloop import FakeLoop
from argos_agent.tui.widgets.code_action import CodeActionBlock
from argos_agent.tui.widgets.transcript import SystemLine, Transcript, UserMessage

# 各类会咬人的方括号内容(控制台 markup 视角下全是"非法标签")。
_BRACKETY = "已点击 \"input[value='Google Search']\" [返回值] [1, 2, 3] list[str] [/not a tag]"


def test_static_widgets_constructed_markup_false():
    """构造期即关 markup —— update() 沿用此设置(Textual 用 _render_markup),从根上免疫。"""
    assert UserMessage(_BRACKETY)._render_markup is False
    assert SystemLine(_BRACKETY)._render_markup is False
    assert CodeActionBlock(code="x=1", step=0) is not None  # 构造不崩


@pytest.mark.asyncio
async def test_code_result_with_brackets_does_not_crash():
    """复现真崩溃路径:CodeResult.value_repr 含 `[...]` 经 _apply_event → set_result 渲染。"""
    app = ArgosApp(loop_factory=lambda: FakeLoop())
    async with app.run_test() as pilot:
        await pilot.pause()
        await app._apply_event(CodeAction(code="print(browser_click('input'))", step=0))
        # 这一步在修复前会抛 MarkupError 崩掉 worker;修复后正常渲染。
        await app._apply_event(CodeResult(step=0, stdout=_BRACKETY, value_repr=_BRACKETY,
                                          exc="", ok=True))
        await pilot.pause()
        assert app.is_running                      # 没崩
        blocks = list(app.query(CodeActionBlock))
        assert blocks and blocks[0].ok is True
        # 结果区把方括号当字面量渲染(内容里能找到原始片段)。
        result = blocks[0].query_one("#result")
        assert "input[value=" in str(result.render())


@pytest.mark.asyncio
async def test_user_and_system_lines_with_brackets_render():
    app = ArgosApp(loop_factory=lambda: FakeLoop())
    async with app.run_test() as pilot:
        await pilot.pause()
        log = app.query_one("#transcript", Transcript)
        await log.user_line("修个 bug:list[int] 和 dict[str, int]")
        await log.append_line(f"工具输出:{_BRACKETY}", kind="error")
        await pilot.pause()
        assert app.is_running                      # 含方括号的用户输入 + 系统行都不崩
        assert "list[int]" in log.rendered_text
