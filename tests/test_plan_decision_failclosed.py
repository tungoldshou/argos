"""Internal documentation."""
from __future__ import annotations

import asyncio

import pytest

from argos.approval import ApprovalLevel
from argos.core.loop import AgentLoop, LoopConfig
from argos.core.plan_mode import EnterPlanMode
from argos.protocol.events import CodeAction, Error, EventBus, PlanRendered

from tests.test_loop_codeact import FakeModel, FakeSandbox, FakeStore, FakeVerifier


def _plan_mode_loop(scripts: list[str]) -> AgentLoop:
    loop = AgentLoop(
        store=FakeStore(), bus=EventBus(), sandbox=FakeSandbox(),
        broker=None, model=FakeModel(scripts), verifier=FakeVerifier(),
        config=LoopConfig(verify_cmd=None, max_steps=3, approval_level=ApprovalLevel.AUTO),
    )
    EnterPlanMode(loop)
    return loop


@pytest.mark.asyncio
async def test_plan_decision_timeout_is_fail_closed():
    """Internal documentation."""
    loop = _plan_mode_loop(["计划:第一步做 X,第二步做 Y。"])
    loop.PLAN_DECISION_TIMEOUT_S = 0.05
    events = []
    with pytest.raises(asyncio.CancelledError):
        async for ev in loop.run("做个东西", session_id="t-timeout"):
            events.append(ev)
    assert any(isinstance(e, PlanRendered) for e in events), "应先产 PlanRendered"
    errs = [e for e in events if isinstance(e, Error)]
    assert errs, "超时必须投诚实 Error 事件"
    assert any("超时" in e.message and "fail-closed" in e.message for e in errs), (
        f"Error 文案须如实说明超时+fail-closed,实得:{[e.message for e in errs]}"
    )
    assert not any(isinstance(e, CodeAction) for e in events), (
        "超时后出现 CodeAction = 计划被自动放行进 act,fail-open 回归!"
    )
    assert loop._plan_call_registry == {}


@pytest.mark.asyncio
async def test_plan_decision_none_is_fail_closed():
    """Internal documentation."""
    loop = _plan_mode_loop(["计划:只有一步。"])
    events = []

    async def _poke_event_after_render():
        await asyncio.sleep(0.05)
        loop._plan_decision_event.set()

    poke = asyncio.ensure_future(_poke_event_after_render())
    try:
        with pytest.raises(asyncio.CancelledError):
            async for ev in loop.run("做个东西", session_id="t-none"):
                events.append(ev)
    finally:
        poke.cancel()
    errs = [e for e in events if isinstance(e, Error)]
    assert any("fail-closed" in e.message for e in errs), "None 防御路径必须诚实 Error"
    assert not any(isinstance(e, CodeAction) for e in events), (
        "decision=None 后出现 CodeAction = 自动 approve 回归,fail-open!"
    )
