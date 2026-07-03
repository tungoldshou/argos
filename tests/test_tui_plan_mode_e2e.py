from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from typing import Any

import pytest

from argos.approval import ApprovalGate, ApprovalLevel
from argos.core.loop import AgentLoop, LoopConfig
from argos.core.plan_mode import (
    EnterPlanMode, ExitPlanMode, PlanExitDecision, PlanRenderer,
)
from argos.core.verify_gate import Verdict
from argos.sandbox.broker import CapabilityBroker
from argos.sandbox.egress import EgressPolicy
from argos.sandbox.executor import SeatbeltExecutor
from argos.tools.receipts import ReceiptSigner
from argos.tui.app import ArgosApp
from argos.tui.events import (
    CodeAction, CodeResult, CostUpdate, Event, EventBus, PhaseChange,
    PlanRendered, PlanUpdate, TokenDelta, VerifyVerdict,
)
from argos.tui.fakeloop import FakeLoop
from argos.tui.widgets.inline_choice import InlineChoice


class _ScriptedModel:
    def __init__(self, scripts: list[str]):
        self._scripts = list(scripts)
        self._i = 0
        self.last_usage: dict = {"input_tokens": 10, "output_tokens": 5}

    async def stream(self, messages, *, system, system_dynamic=None):
        text = self._scripts[min(self._i, len(self._scripts) - 1)]
        self._i += 1
        for ch in text:
            yield ch


class _NoopSandbox:
    def __init__(self):
        self.codes: list[str] = []
    def spawn(self, *, workspace, namespace, allow_workflow=True, read_only=False):
        pass
    def exec_code(self, code):
        from argos.sandbox.backend import ExecResult
        self.codes.append(code)
        return ExecResult(stdout="ok", value_repr="", exc="")
    def close(self): pass


class _PassVerifier:
    def verify(self, verify_cmd, *, attempts=1):
        return Verdict.passed(detail="[exit_code=0]", verify_cmd=verify_cmd, attempts=attempts)


class _RecordingStore:
    def __init__(self):
        self.events: list = []
        self.messages: list[dict] = []
        self.session_ensured = False
    def append_event(self, sid, ev):
        self.events.append(ev)
    def append_message(self, sid, *, role, content, **kwargs):
        self.messages.append({"role": role, "content": content})
        return f"m{len(self.messages)}"
    def ensure_session(self, sid, **kwargs):
        self.session_ensured = True
    def get_messages(self, sid):
        return list(self.messages)


def _build_real_plan_loop(store, in_project, scripts):
    gate = ApprovalGate(level=ApprovalLevel.AUTO)
    broker = CapabilityBroker(
        gate=gate,
        egress=EgressPolicy(llm_hosts=set(), search_hosts=set(), mcp_hosts=set()),
        signer=ReceiptSigner(key=b"e2e-key"),
    )
    sandbox = _NoopSandbox()
    model = _ScriptedModel(scripts)
    cfg = LoopConfig(model_tier="worker", verify_cmd=None, max_rounds=2,
                     max_steps=10, compaction=False, approval_level=ApprovalLevel.AUTO)
    return AgentLoop(store=store, bus=EventBus(), sandbox=sandbox, broker=broker,
                     model=model, verifier=_PassVerifier(), config=cfg,
                     workspace=in_project, verify_dir=in_project)


@pytest.fixture
def e2e_loop_factory():
    store = _RecordingStore()
    in_project = None
    def factory(loop: AgentLoop) -> AgentLoop:
        return loop
    return store, in_project, factory


@pytest.mark.asyncio
async def test_e2e_plan_to_approve_to_completion(e2e_loop_factory, tmp_path):
    store, _in_project, _ = e2e_loop_factory
    loop = _build_real_plan_loop(
        store, None,
        scripts=[
            "计划:我会读 a.py 然后写 hello",
            "```python\npass\n```",
            "完成。",
        ],
    )
    EnterPlanMode(loop)
    assert loop.mode == "plan", "EnterPlanMode 后 mode 应是 plan"

    run_task = asyncio.create_task(_drain(loop, "读 a.py", store))
    plan_rendered = await _wait_for_event(store, PlanRendered, timeout=3.0)
    assert plan_rendered is not None, "loop 跑 plan 阶段应投 PlanRendered 事件"
    assert "读 a.py" in plan_rendered.plan_md or "读 a" in plan_rendered.plan_md, (
        f"plan 文档应含 goal,实际:\n{plan_rendered.plan_md}"
    )

    ExitPlanMode(loop, "approve_start")
    assert loop._plan_decision == PlanExitDecision(action="approve_start")
    loop._plan_decision_event.set()

    await asyncio.wait_for(run_task, timeout=5.0)

    kinds = [type(ev).__name__ for ev in store.events]
    assert "PhaseChange" in kinds, "应至少有 PhaseChange 事件"
    phase_seq = [ev.phase for ev in store.events if isinstance(ev, PhaseChange)]
    assert "plan" in phase_seq, f"phase 序列应含 plan: {phase_seq}"
    assert "act" in phase_seq, f"phase 序列应含 act: {phase_seq}"
    assert "verify" in phase_seq, f"phase 序列应含 verify: {phase_seq}"
    assert "report" in phase_seq, f"phase 序列应含 report: {phase_seq}"
    plan_idx = phase_seq.index("plan")
    act_idx = phase_seq.index("act")
    assert plan_idx < act_idx, f"plan 必在 act 之前: plan={plan_idx} act={act_idx}"


@pytest.mark.asyncio
async def test_e2e_plan_modal_pushed_on_screen_and_dismissed_on_key_1(e2e_loop_factory, tmp_path):
    store, _in_project, _ = e2e_loop_factory

    class _MiniLoop:
        def __init__(self):
            self.mode = "plan"
            self._plan_decision_event = asyncio.Event()
            self._plan_decision: PlanExitDecision | None = None
            self._approval_level_override = None

        async def run(self, goal: str, session_id: str) -> AsyncIterator[Event]:
            yield PhaseChange(phase="plan", actions=0)
            yield TokenDelta(text=f"计划:{goal}\n")
            yield PlanRendered(plan_md=PlanRenderer.render(goal=goal, todos=[], tool_calls=[]))
            await self._plan_decision_event.wait()
            yield PhaseChange(phase="act", actions=1)
            yield TokenDelta(text="干活中\n")
            yield PhaseChange(phase="verify", actions=1)
            yield VerifyVerdict(verdict=Verdict.passed(detail="ok", verify_cmd="echo ok", attempts=1))
            yield PhaseChange(phase="report", actions=1)
            yield CostUpdate(tokens_in=10, tokens_out=5, cost_usd=0.0, elapsed_s=0.1)

    loop = _MiniLoop()
    app = ArgosApp(loop_factory=lambda **kw: loop,
                   gate=ApprovalGate(ApprovalLevel.CONFIRM))
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        app._plan_mode = True
        app.handle_input("读 a.py")
        for _ in range(50):
            await pilot.pause()
            if bool(app.query(InlineChoice)):
                break
        assert bool(app.query(InlineChoice)), (
            f"PlanRendered 后 InlineChoice 应挂在流内,实际 {app.query(InlineChoice)}"
        )
        await pilot.press("1")
        for _ in range(50):
            await pilot.pause()
            if loop._plan_decision is not None:
                break
        assert loop._plan_decision is not None
        assert loop._plan_decision.action == "approve_start"


# ── helpers ──
async def _drain(loop: AgentLoop, goal: str, store: _RecordingStore) -> None:
    async for ev in loop.run(goal, "sess-e2e"):
        store.append_event("sess-e2e", ev)


async def _wait_for_event(store: _RecordingStore, kind: type, *, timeout: float) -> Any:
    deadline = asyncio.get_event_loop().time() + timeout
    while asyncio.get_event_loop().time() < deadline:
        for ev in store.events:
            if isinstance(ev, kind):
                return ev
        await asyncio.sleep(0.05)
    return None
