from __future__ import annotations

from collections.abc import AsyncIterator
from unittest.mock import MagicMock

import pytest

from argos.approval import ApprovalGate, ApprovalLevel
from argos.core.plan_mode import EnterPlanMode, PlanExitDecision
from argos.tui.app import ArgosApp
from argos.tui.events import (
    Event, PlanRendered, PhaseChange, TokenDelta, VerifyVerdict, CostUpdate,
)
from argos.tui.fakeloop import FakeLoop
from argos.tui.widgets.inline_choice import InlineChoice


class _PlanRenderedLoop:

    def __init__(self) -> None:
        self._mode = "plan"
        self._plan_decision_event = __import__("asyncio").Event()
        self._plan_decision = None
        self._approval_level_override = None
        self.mode = "plan"
        self._busy = False

    async def run(self, goal: str, session_id: str) -> AsyncIterator[Event]:
        yield PhaseChange(phase="plan", actions=0)
        yield TokenDelta(text=f"我会按目标做事:{goal}\n")
        from argos.core.plan_mode import PlanRenderer
        plan_md = PlanRenderer.render(goal=goal, todos=[], tool_calls=[])
        yield PlanRendered(plan_md=plan_md)
        await self._plan_decision_event.wait()
        yield PhaseChange(phase="act", actions=1)
        yield TokenDelta(text="干活中\n")
        yield PhaseChange(phase="verify", actions=1)
        from argos.core.verify_gate import Verdict
        yield VerifyVerdict(verdict=Verdict.passed(detail="ok", verify_cmd="echo ok", attempts=1))
        yield PhaseChange(phase="report", actions=1)
        yield CostUpdate(tokens_in=10, tokens_out=5, cost_usd=0.0, elapsed_s=0.1)


def test_plan_renderer_omits_empty_tool_call_preview():
    from argos.core.plan_mode import PlanRenderer

    plan_md = PlanRenderer.render(goal="读 a.py", todos=[], tool_calls=[])
    assert "tool_calls" not in plan_md
    assert "工具调用" not in plan_md


@pytest.mark.asyncio
async def test_plan_rendered_event_pushes_plan_modal():
    loop = _PlanRenderedLoop()
    app = ArgosApp(loop_factory=lambda **kw: loop,
                   gate=ApprovalGate(ApprovalLevel.CONFIRM))
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        app._plan_mode = True
        app.handle_input("读 a.py")
        for _ in range(30):
            await pilot.pause()
            if bool(app.query(InlineChoice)):
                break
        assert bool(app.query(InlineChoice)), (
            f"PlanRendered 后 InlineChoice 应挂在流内,实际={app.query(InlineChoice)}"
        )
        await pilot.press("1")
        await pilot.pause()
        await pilot.pause()


@pytest.mark.asyncio
async def test_modal_decision_calls_exit_plan_mode_with_approve_start():
    loop = _PlanRenderedLoop()
    app = ArgosApp(loop_factory=lambda **kw: loop,
                   gate=ApprovalGate(ApprovalLevel.CONFIRM))
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        app._plan_mode = True
        app.handle_input("读 a.py")
        for _ in range(30):
            await pilot.pause()
            if bool(app.query(InlineChoice)):
                break
        await pilot.press("1")   # Approve and start
        for _ in range(30):
            await pilot.pause()
            if loop._plan_decision is not None:
                break
        assert loop._plan_decision is not None, "1 键后 _plan_decision 应被写"
        assert loop._plan_decision.action == "approve_start"


@pytest.mark.asyncio
async def test_modal_decision_keep_planning_wakes_loop_for_another_round():
    loop = _PlanRenderedLoop()
    app = ArgosApp(loop_factory=lambda **kw: loop,
                   gate=ApprovalGate(ApprovalLevel.CONFIRM))
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        app._plan_mode = True
        app.handle_input("读 a.py")
        for _ in range(30):
            await pilot.pause()
            if bool(app.query(InlineChoice)):
                break
        await pilot.press("3")   # Keep planning
        for _ in range(30):
            await pilot.pause()
            if loop._plan_decision is not None:
                break
        assert loop._plan_decision is not None
        assert loop._plan_decision.action == "keep_planning"
