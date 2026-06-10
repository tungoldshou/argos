"""InlineChoice 流内选择组件(TUI v2 spec §4)单元 + plan 决策 4 选项 + FIFO 队列。

取代旧 PlanModal/ApprovalModal/WorkflowApprovalModal 测试中的交互面:
↑↓+Enter / 数字直选 / Esc / refine 就地反馈输入 / 到达铃声 / 决策幂等 / app 队列。
"""
from __future__ import annotations

import pytest
from textual.app import App, ComposeResult

from argos_agent.approval import ApprovalGate, ApprovalLevel
from argos_agent.tui.app import ArgosApp
from argos_agent.tui.events import ApprovalRequest
from argos_agent.tui.fakeloop import FakeLoop
from argos_agent.tui.widgets.inline_choice import InlineChoice

_PLAN_OPTIONS = [
    ("approve_start", "Approve and start"),
    ("approve_accept_edits", "Approve and accept edits"),
    ("keep_planning", "Keep planning"),
    ("refine", "Refine with feedback"),
]


class _Host(App):
    def __init__(self, **kw) -> None:
        super().__init__()
        self._kw = kw
        self.decisions: list[tuple[str, str]] = []

    def compose(self) -> ComposeResult:
        kw = dict(
            title="📋 Plan 审批", body="# Plan\n...",
            options=list(_PLAN_OPTIONS),
            on_decide=lambda v, f: self.decisions.append((v, f)),
            escape_value=None,
            needs_input={"refine"},
        )
        kw.update(self._kw)
        yield InlineChoice(**kw)


@pytest.mark.asyncio
async def test_plan_options_render_and_digit_select():
    app = _Host()
    async with app.run_test() as pilot:
        await pilot.pause()
        c = app.query_one(InlineChoice)
        opts = str(c.query_one("#ic-options").render())
        for _, label in _PLAN_OPTIONS:
            assert label in opts
        await pilot.press("3")
        await pilot.pause()
        assert app.decisions == [("keep_planning", "")]


@pytest.mark.asyncio
async def test_arrow_navigation_wraps_and_enter_confirms():
    app = _Host()
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("up")      # 从 0 上卷到最后一项之前先验证回绕
        await pilot.pause()
        c = app.query_one(InlineChoice)
        assert c._cursor == len(_PLAN_OPTIONS) - 1  # 回绕到末项(refine)
        await pilot.press("down")    # 回到 0
        await pilot.press("down")    # 1
        await pilot.press("enter")
        await pilot.pause()
        assert app.decisions == [("approve_accept_edits", "")]


@pytest.mark.asyncio
async def test_refine_expands_input_and_submits_feedback():
    """选 refine → 就地展开反馈输入 → Enter 提交带 feedback(不再返空串假反馈)。"""
    app = _Host()
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("4")       # refine(needs_input)→ 不立即决策
        await pilot.pause()
        c = app.query_one(InlineChoice)
        assert app.decisions == []
        assert c.has_class("-input-mode")
        for ch in "abc":
            await pilot.press(ch)
        await pilot.press("enter")
        await pilot.pause()
        assert app.decisions == [("refine", "abc")]


@pytest.mark.asyncio
async def test_refine_input_escape_returns_to_options():
    app = _Host()
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("4")
        await pilot.pause()
        c = app.query_one(InlineChoice)
        assert c.has_class("-input-mode")
        await pilot.press("escape")
        await pilot.pause()
        assert not c.has_class("-input-mode")
        assert app.decisions == []
        await pilot.press("1")       # 回选项后仍可正常决策
        await pilot.pause()
        assert app.decisions == [("approve_start", "")]


@pytest.mark.asyncio
async def test_escape_ignored_without_escape_value():
    """plan 决策无"安全默认":Esc 不产生决策(用户没拍就让 loop 继续挂,诚实)。"""
    app = _Host()
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("escape")
        await pilot.pause()
        assert app.decisions == []
        assert app.query(InlineChoice)   # 组件仍在


@pytest.mark.asyncio
async def test_decision_is_idempotent_and_removes_widget():
    app = _Host()
    async with app.run_test() as pilot:
        await pilot.pause()
        c = app.query_one(InlineChoice)
        await pilot.press("1")
        await pilot.pause()
        assert not list(app.query(InlineChoice)), "决策后组件应自毁"
        c._finish("approve_start", "")   # 直接二次触发 → 幂等不双发
        assert app.decisions == [("approve_start", "")]


@pytest.mark.asyncio
async def test_bell_rings_on_mount(monkeypatch):
    """到达提示音:mount 时调 app.bell()(用户明确要求的音效)。"""
    rang: list[bool] = []
    app = _Host()
    monkeypatch.setattr(type(app), "bell", lambda self: rang.append(True))
    async with app.run_test() as pilot:
        await pilot.pause()
        assert rang, "InlineChoice mount 应触发终端铃"


@pytest.mark.asyncio
async def test_app_queue_serializes_two_approvals():
    """app FIFO:两个 ApprovalRequest 并发到达 → 同屏只渲染一个;前一个决策后第二个才出现。"""
    gate = ApprovalGate(ApprovalLevel.CONFIRM)
    app = ArgosApp(loop_factory=lambda: FakeLoop(), gate=gate)
    r1 = ApprovalRequest(call_id="c1", action="run_command", args={"command": "a"},
                         description="a", risk="low")
    r2 = ApprovalRequest(call_id="c2", action="run_command", args={"command": "b"},
                         description="b", risk="low")
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        await app._handle_approval(r1)
        await app._handle_approval(r2)
        await pilot.pause()
        assert len(list(app.query(InlineChoice))) == 1, "同屏最多一个活动 InlineChoice"
        await pilot.press("1")        # 决 r1
        for _ in range(20):
            await pilot.pause()
            if len(list(app.query(InlineChoice))) == 1:
                break
        assert len(list(app.query(InlineChoice))) == 1, "r1 决策后 r2 应从队列 mount"
        await pilot.press("4")        # 决 r2(deny)收尾
        await pilot.pause()


@pytest.mark.asyncio
async def test_focus_returns_to_prompt_after_decision():
    """决策后焦点还给 #prompt(输入草稿不丢)。"""
    gate = ApprovalGate(ApprovalLevel.CONFIRM)
    app = ArgosApp(loop_factory=lambda: FakeLoop(), gate=gate)
    req = ApprovalRequest(call_id="c1", action="run_command", args={"command": "a"},
                          description="a", risk="low")
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        await app._handle_approval(req)
        await pilot.pause()
        c = app.query_one(InlineChoice)
        assert app.focused is c, "审批挂起时 InlineChoice 应夺焦"
        await pilot.press("1")
        await pilot.pause()
        assert app.focused is not None and app.focused.id == "prompt"
