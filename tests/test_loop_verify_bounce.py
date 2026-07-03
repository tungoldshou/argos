from __future__ import annotations

import pytest

from argos.core.loop import AgentLoop, LoopConfig
from argos.core.verify_gate import Verdict
from argos.sandbox.backend import ExecResult
from argos.tui.events import Escalation, EventBus, PhaseChange, VerifyVerdict


class FakeModel:
    def __init__(self):
        self.calls = 0
    async def stream(self, messages, *, system, system_dynamic=None):
        self.calls += 1
        for ch in "我觉得完成了。":
            yield ch


class FakeSandbox:
    def spawn(self, *, workspace, namespace, allow_workflow=True, read_only=False): ...
    def exec_code(self, code): return ExecResult(stdout="", value_repr="", exc="")
    def close(self): ...


class FailingVerifier:
    def verify(self, verify_cmd, *, attempts=1):
        return Verdict.failed(
            detail="[exit_code=1]\nassert False",
            verify_cmd=verify_cmd, attempts=attempts,
        )


class FakeStore:
    def append_event(self, sid, ev): ...
    def append_message(self, sid, **kw): return "m0"


class NonConformingPassedVerifier:
    def verify(self, verify_cmd, *, attempts=1):
        return Verdict.passed(detail="[non-conforming]", verify_cmd=verify_cmd, attempts=attempts)


class CompletingModel:
    def __init__(self):
        self._i = 0

    async def stream(self, messages, *, system, system_dynamic=None):
        scripts = ["```python\nwrite_file('out.txt', 'done')\n```", "任务完成了。"]
        t = scripts[min(self._i, len(scripts) - 1)]
        self._i += 1
        for ch in t:
            yield ch


@pytest.mark.asyncio
async def test_loop_no_verify_cmd_nonconforming_verifier_honest_completion():
    loop = AgentLoop(
        store=FakeStore(), bus=EventBus(), sandbox=FakeSandbox(), broker=None,
        model=CompletingModel(), verifier=NonConformingPassedVerifier(),
        config=LoopConfig(verify_cmd=None, max_rounds=3, max_steps=10),
    )
    events = [ev async for ev in loop.run("无测任务", "s")]
    phase_changes = [ev.phase for ev in events if isinstance(ev, PhaseChange)]
    verdicts = [ev.verdict for ev in events if isinstance(ev, VerifyVerdict)]
    escalations = [ev for ev in events if isinstance(ev, Escalation)]

    assert "report" in phase_changes, "loop 必须正常收尾进入 report 阶段"
    assert verdicts, "必须经过 verify 门"
    assert not escalations, "无测任务绝不应触发 Escalation"
    assert phase_changes[-1] == "report", "最终阶段必须是 report"


@pytest.mark.asyncio
async def test_verify_failure_bounces_then_escalates():
    loop = AgentLoop(
        store=FakeStore(), bus=EventBus(), sandbox=FakeSandbox(), broker=None,
        model=FakeModel(), verifier=FailingVerifier(),
        config=LoopConfig(verify_cmd="pytest -q", max_rounds=2, max_steps=10),
    )
    verdicts = []
    escalation = None
    async for ev in loop.run("修复 bug", "s"):
        if isinstance(ev, VerifyVerdict):
            verdicts.append(ev.verdict)
        if isinstance(ev, Escalation):
            escalation = ev
    assert escalation is not None
    assert escalation.attempts >= 2
    assert "pytest -q" in escalation.last_failure or "exit_code=1" in escalation.last_failure
