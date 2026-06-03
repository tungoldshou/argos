"""Phase 3:称完成→verify 失败 bounce→超 max_rounds→诚实 Escalation(契约 §3 + spec §3.3)。"""
from __future__ import annotations

import pytest

from argos_agent.core.loop import AgentLoop, LoopConfig
from argos_agent.core.verify_gate import Verdict
from argos_agent.sandbox.backend import ExecResult
from argos_agent.tui.events import Escalation, EventBus, VerifyVerdict


class FakeModel:
    def __init__(self):
        self.calls = 0
    async def stream(self, messages, *, system):
        self.calls += 1
        # 每次都"宣布完成"(无代码块)→ 触发 verify;验证总失败 → 反复 bounce。
        for ch in "我觉得完成了。":
            yield ch


class FakeSandbox:
    def spawn(self, *, workspace, namespace): ...
    def exec_code(self, code): return ExecResult(stdout="", value_repr="", exc="")
    def close(self): ...


class FailingVerifier:
    """契约 §9 锁#1 canonical 签名: verify(verify_cmd, *, attempts=1) -> Verdict"""
    def verify(self, verify_cmd, *, attempts=1):
        return Verdict.failed(
            detail="[exit_code=1]\nassert False",
            verify_cmd=verify_cmd, attempts=attempts,
        )


class FakeStore:
    def append_event(self, sid, ev): ...
    def append_message(self, sid, **kw): return "m0"


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
    # 验证失败 → bounce → 达 max_rounds(2)→ 诚实升级
    assert escalation is not None
    assert escalation.attempts >= 2
    assert "pytest -q" in escalation.last_failure or "exit_code=1" in escalation.last_failure
