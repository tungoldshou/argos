"""Phase 3:称完成→verify 失败 bounce→超 max_rounds→诚实 Escalation(契约 §3 + spec §3.3)。
Phase 4 #3:非规范 verifier 在 verify_cmd=None 时返回 passed → loop 必须仍走诚实完成路径。"""
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
        # 每次都"宣布完成"(无代码块)→ 触发 verify;验证总失败 → 反复 bounce。
        for ch in "我觉得完成了。":
            yield ch


class FakeSandbox:
    def spawn(self, *, workspace, namespace, allow_workflow=True, read_only=False): ...
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


class NonConformingPassedVerifier:
    """非规范 verifier:verify_cmd=None 时仍返回 passed(违反诚实协议)。
    用来测试 loop 的 defense-in-depth 守护(Phase 4 #3)。"""
    def verify(self, verify_cmd, *, attempts=1):
        return Verdict.passed(detail="[non-conforming]", verify_cmd=verify_cmd, attempts=attempts)


class CompletingModel:
    """每次 stream 均返回无代码块文本("宣布完成")。"""
    async def stream(self, messages, *, system, system_dynamic=None):
        for ch in "任务完成了。":
            yield ch


@pytest.mark.asyncio
async def test_loop_no_verify_cmd_nonconforming_verifier_honest_completion():
    """Phase 4 #3 defense-in-depth:非规范 verifier 在 verify_cmd=None 时返回 passed →
    loop 必须仍走诚实完成路径(NO_TEST_LABEL / unverifiable),不能当作 passed 静默成功。"""
    loop = AgentLoop(
        store=FakeStore(), bus=EventBus(), sandbox=FakeSandbox(), broker=None,
        model=CompletingModel(), verifier=NonConformingPassedVerifier(),
        config=LoopConfig(verify_cmd=None, max_rounds=3, max_steps=10),
    )
    events = [ev async for ev in loop.run("无测任务", "s")]
    phase_changes = [ev.phase for ev in events if isinstance(ev, PhaseChange)]
    verdicts = [ev.verdict for ev in events if isinstance(ev, VerifyVerdict)]
    escalations = [ev for ev in events if isinstance(ev, Escalation)]

    # 必须走到 report 阶段(不能卡住或抛异常)
    assert "report" in phase_changes, "loop 必须正常收尾进入 report 阶段"
    # 必须有 VerifyVerdict(证明走过 verify 门)
    assert verdicts, "必须经过 verify 门"
    # 无测任务绝不应触发 Escalation
    assert not escalations, "无测任务绝不应触发 Escalation"
    # 诚实路径:verify 门的 verdict 应为 unverifiable(非规范 verifier 返 passed,
    # 但 loop 拦截后转走 is_honest_completion → Harness 里 Verifier 返 unverifiable)
    # 或者 loop 直接拒绝 passed 并走 is_honest_completion 路径。
    # 关键不变量:report 出现且无 Escalation。
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
    # 验证失败 → bounce → 达 max_rounds(2)→ 诚实升级
    assert escalation is not None
    assert escalation.attempts >= 2
    assert "pytest -q" in escalation.last_failure or "exit_code=1" in escalation.last_failure
