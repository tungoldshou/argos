"""Plan 决策 fail-closed 回归钉(P3a 终审 major #1/#2 的防翻面测试)。

钉死两条护城河语义,防止未来重构把兜底方向悄悄翻回 fail-open:
  · 决策超时(daemon 客户端断连/不应答) → 诚实 Error + CancelledError 取消 run,
    【绝不】把超时当 approve_start 放行计划进 act。
  · _plan_decision 为 None 的防御路径 → 同样 fail-closed 取消,不自动 approve。

夹具来源:tests/test_loop_codeact.py(同 test_loop_plan_mode_render.py 策略)。
"""
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
    """超时 → 诚实 Error(含'超时'与 fail-closed 字样)+ CancelledError;绝不进 act。"""
    loop = _plan_mode_loop(["计划:第一步做 X,第二步做 Y。"])
    loop.PLAN_DECISION_TIMEOUT_S = 0.05   # 实例覆盖类常量,加速测试
    events = []
    with pytest.raises(asyncio.CancelledError):
        async for ev in loop.run("做个东西", session_id="t-timeout"):
            events.append(ev)
    # 走过 plan 渲染
    assert any(isinstance(e, PlanRendered) for e in events), "应先产 PlanRendered"
    # 诚实超时 Error
    errs = [e for e in events if isinstance(e, Error)]
    assert errs, "超时必须投诚实 Error 事件"
    assert any("超时" in e.message and "fail-closed" in e.message for e in errs), (
        f"Error 文案须如实说明超时+fail-closed,实得:{[e.message for e in errs]}"
    )
    # 反 fail-open 铁证:绝不进 act(无任何代码动作)
    assert not any(isinstance(e, CodeAction) for e in events), (
        "超时后出现 CodeAction = 计划被自动放行进 act,fail-open 回归!"
    )
    # 注册表清空(防残留 call_id 复用)
    assert loop._plan_call_registry == {}


@pytest.mark.asyncio
async def test_plan_decision_none_is_fail_closed():
    """决策事件被 set 但 _plan_decision 为 None(防御路径)→ 同样 fail-closed 取消。"""
    loop = _plan_mode_loop(["计划:只有一步。"])
    events = []

    async def _poke_event_after_render():
        # 等 plan 渲染挂起后,只 set event 不写 decision(模拟内部错误)。
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
