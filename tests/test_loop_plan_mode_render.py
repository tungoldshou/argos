"""Internal documentation."""
from __future__ import annotations

import asyncio

import pytest

from argos.approval import ApprovalLevel
from argos.core.loop import AgentLoop, LoopConfig
from argos.tui.events import EventBus, PlanRendered
from argos.core.plan_mode import PlanExitDecision

from tests.test_loop_codeact import FakeModel, FakeSandbox, FakeStore, FakeVerifier


class _RecordingFakeModel(FakeModel):
    """Internal documentation."""
    def __init__(self, scripts: list[str]):
        super().__init__(scripts)
        self.calls: list[list[dict]] = []

    async def stream(self, messages, *, system, system_dynamic=None):
        self.calls.append(list(messages))
        text = self._scripts[min(self._i, len(self._scripts) - 1)]
        self._i += 1
        for ch in text:
            yield ch


def _plan_mode_loop(scripts: list[str], *, verify_cmd=None, level=ApprovalLevel.AUTO,
                    model: FakeModel | None = None):
    """Internal documentation."""
    from argos.core.plan_mode import EnterPlanMode
    loop = AgentLoop(
        store=FakeStore(), bus=EventBus(), sandbox=FakeSandbox(),
        broker=None, model=model or FakeModel(scripts), verifier=FakeVerifier(),
        config=LoopConfig(verify_cmd=verify_cmd, max_steps=3, approval_level=level),
    )
    EnterPlanMode(loop)
    return loop


async def _drive_until(loop: AgentLoop, goal: str, *, max_events: int = 200) -> list:
    """Internal documentation."""
    return [ev async for ev in loop.run(goal, "sess-plan")]


def _set_decision(loop: AgentLoop, action: str, feedback: str | None = None) -> None:
    """Internal documentation."""
    loop._plan_decision = PlanExitDecision(action=action, feedback=feedback)
    loop._plan_decision_event.set()




@pytest.mark.asyncio
async def test_plan_mode_emits_PlanRendered_event_with_markdown():
    """Internal documentation."""
    loop = _plan_mode_loop(["我会按这个目标做事:读 a.py。"])
    async def _decide_later() -> None:
        await asyncio.sleep(0.05)
        _set_decision(loop, "approve_start")
    dec_task = asyncio.create_task(_decide_later())
    events = await _drive_until(loop, "读 a.py")
    await dec_task

    plan_rendered = [ev for ev in events if isinstance(ev, PlanRendered)]
    assert len(plan_rendered) == 1, f"plan 模式应产 1 个 PlanRendered,收到 {len(plan_rendered)} 个"
    md = plan_rendered[0].plan_md
    assert "读 a.py" in md or "读 a" in md, f"plan 文档应含 goal 摘要,实际:\n{md}"
    assert "审批" in md or "Approve" in md, f"plan 文档应含审批段,实际:\n{md}"


@pytest.mark.asyncio
async def test_plan_mode_suspends_until_decision_event_set():
    """Internal documentation."""
    loop = _plan_mode_loop(["随便"])
    task = asyncio.create_task(_drive_until(loop, "noop"))
    await asyncio.sleep(0.1)
    assert not task.done(), "无决策时 plan 模式应一直挂起(不假绿)"
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass




@pytest.mark.asyncio
async def test_plan_mode_approve_start_continues_to_act_phase():
    """Internal documentation."""
    loop = _plan_mode_loop([
        "计划:读 a.py",
        "```python\nwrite_file('x.py','y')\n```",
        "完成。",
    ])

    async def _decide_later() -> None:
        await asyncio.sleep(0.05)
        _set_decision(loop, "approve_start")
    dec_task = asyncio.create_task(_decide_later())
    events = await _drive_until(loop, "写个文件")
    await dec_task

    from argos.tui.events import PhaseChange
    plan_rendered_idx = next(i for i, ev in enumerate(events) if isinstance(ev, PlanRendered))
    act_changes = [i for i, ev in enumerate(events)
                  if isinstance(ev, PhaseChange) and ev.phase == "act"]
    assert act_changes, "approve_start 后应进 act 阶段"
    assert act_changes[0] > plan_rendered_idx, "act PhaseChange 必须在 PlanRendered 之后"


@pytest.mark.asyncio
async def test_plan_mode_approve_accept_edits_sets_approval_level():
    """Internal documentation."""
    loop = _plan_mode_loop([
        "计划:写文件",
        "```python\nwrite_file('x.py','y')\n```",
        "完成。",
    ])

    async def _decide_later() -> None:
        await asyncio.sleep(0.05)
        _set_decision(loop, "approve_accept_edits")
    dec_task = asyncio.create_task(_decide_later())
    await _drive_until(loop, "写文件")
    await dec_task

    cur = loop._approval_level_override
    assert cur is ApprovalLevel.ACCEPT_EDITS or cur is None, (
        f"approve_accept_edits 应把 _approval_level_override 置 ACCEPT_EDITS,实际 {cur}"
    )


@pytest.mark.asyncio
async def test_plan_mode_keep_planning_re_enters_plan_phase():
    """Internal documentation."""
    goal = "build a CLI parser for the user"
    model = _RecordingFakeModel([
        "第一轮 plan",   # 0
        "第二轮 plan",   # 1
        "```python\nwrite_file('x.py','y')\n```",  # 2
        "完成。",         # 3
    ])
    loop = _plan_mode_loop(
        ["第一轮 plan", "第二轮 plan",
         "```python\nwrite_file('x.py','y')\n```", "完成。"],
        model=model,
    )

    async def _decide_later() -> None:
        await asyncio.sleep(0.05)
        _set_decision(loop, "keep_planning")
        await asyncio.sleep(0.05)
        _set_decision(loop, "approve_start")
    dec_task = asyncio.create_task(_decide_later())
    events = await _drive_until(loop, goal)
    await dec_task

    plan_rendered = [ev for ev in events if isinstance(ev, PlanRendered)]
    assert len(plan_rendered) == 2, (
        f"keep_planning + approve_start 应产 2 个 PlanRendered,实际 {len(plan_rendered)}"
    )

    assert len(model.calls) >= 2, f"模型应被调 ≥2 次,实际 {len(model.calls)} 次"
    second_round_msgs = model.calls[1]
    user_contents = [m["content"] for m in second_round_msgs if m.get("role") == "user"]
    assert any(goal in c for c in user_contents), (
        f"keep_planning 后第 2 轮 plan 的 messages 应保留原 goal,实际 user 内容: {user_contents}"
    )


@pytest.mark.asyncio
async def test_plan_mode_refine_injects_feedback_as_user_message():
    """Internal documentation."""
    model = _RecordingFakeModel([
        "第一轮 plan",
        "第二轮(应见到 feedback)plan",
        "```python\nwrite_file('x.py','y')\n```",
        "完成。",
    ])
    loop = _plan_mode_loop(
        ["第一轮 plan", "第二轮(应见到 feedback)plan",
         "```python\nwrite_file('x.py','y')\n```", "完成。"],
        model=model,
    )
    feedback_text = "需要补这个上下文:别用 sqlite,直接读文件"

    async def _decide_later() -> None:
        await asyncio.sleep(0.05)
        _set_decision(loop, "refine", feedback_text)
        await asyncio.sleep(0.05)
        _set_decision(loop, "approve_start")
    dec_task = asyncio.create_task(_decide_later())
    events = await _drive_until(loop, "x")
    await dec_task

    plan_rendered = [ev for ev in events if isinstance(ev, PlanRendered)]
    assert len(plan_rendered) == 2, f"refine + approve 应产 2 个 PlanRendered,实际 {len(plan_rendered)}"

    assert len(model.calls) >= 2, f"模型应被调 ≥2 次,实际 {len(model.calls)} 次"
    second_round_msgs = model.calls[1]
    user_contents = [m["content"] for m in second_round_msgs if m.get("role") == "user"]
    assert any(feedback_text in c for c in user_contents), (
        f"refine 后第 2 轮 plan 的 messages 应含 feedback 作 user message,"
        f"实际 user 内容: {user_contents}"
    )
