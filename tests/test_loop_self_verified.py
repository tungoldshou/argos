"""Internal documentation."""
from __future__ import annotations

import pytest

from argos.core.loop import AgentLoop, LoopConfig
from argos.core.verify_gate import Verdict
from argos.sandbox.backend import ExecResult
from argos.tui.events import Escalation, EventBus, PhaseChange, VerifyVerdict


class CompletingModel:
    """Internal documentation."""
    def __init__(self):
        self.calls = 0

    async def stream(self, messages, *, system, system_dynamic=None):
        self.calls += 1
        for ch in "我觉得完成了。":
            yield ch


class WorkingThenCompletingModel:
    """Internal documentation."""
    def __init__(self):
        self.calls = 0
        self.code_emitted = 0

    async def stream(self, messages, *, system, system_dynamic=None):
        self.calls += 1
        if self.code_emitted < 6:
            self.code_emitted += 1
            yield f"```python\nx_{self.code_emitted} = {self.code_emitted}\n```\n"
            return
        for ch in "任务完成了。":
            yield ch


class FakeSandbox:
    def spawn(self, *, workspace, namespace, allow_workflow=True, read_only=False): ...
    def exec_code(self, code): return ExecResult(stdout="", value_repr="", exc="")
    def close(self): ...


class FakeStore:
    def append_event(self, sid, ev): ...
    def append_message(self, sid, **kw): return "m0"


class SelfPassedVerifier:
    """Internal documentation."""
    def __init__(self):
        self.calls = 0

    def verify(self, verify_cmd, *, attempts=1):
        self.calls += 1
        return Verdict.passed_self(
            detail="[self_verified] 自造测试真过了",
            verify_cmd=verify_cmd, attempts=attempts,
        )


class UserPassedVerifier:
    """Internal documentation."""
    def __init__(self):
        self.calls = 0

    def verify(self, verify_cmd, *, attempts=1):
        self.calls += 1
        return Verdict.passed(
            detail="[exit_code=0]",
            verify_cmd=verify_cmd, attempts=attempts,
        )




@pytest.mark.asyncio
async def test_loop_self_verified_pass_does_not_break_as_user_verified(monkeypatch):
    """Internal documentation."""
    monkeypatch.setenv("ARGOS_NO_MEMORY", "1")
    verifier = SelfPassedVerifier()
    loop = AgentLoop(
        store=FakeStore(), bus=EventBus(), sandbox=FakeSandbox(), broker=None,
        model=CompletingModel(), verifier=verifier,
        config=LoopConfig(verify_cmd="pytest -q", max_rounds=2, max_steps=20),
    )
    escalations: list[Escalation] = []
    verdicts: list[Verdict] = []
    async for ev in loop.run("写个 fix", "s"):
        if isinstance(ev, VerifyVerdict):
            verdicts.append(ev.verdict)
        if isinstance(ev, Escalation):
            escalations.append(ev)

    assert verifier.calls >= 1, "verifier 应当被反复调用(防火墙:不把 self_verified 当 break 信号)"
    assert escalations, "C1 修复后,self_verified 不得 break → 必走 bounce→escalation"
    assert any(getattr(v, "self_verified", False) for v in verdicts),\
        "verdict 流里至少一个应带 self_verified=True"


@pytest.mark.asyncio
async def test_loop_user_verified_pass_breaks_normally(monkeypatch):
    """Internal documentation."""
    monkeypatch.setenv("ARGOS_NO_MEMORY", "1")
    verifier = UserPassedVerifier()
    loop = AgentLoop(
        store=FakeStore(), bus=EventBus(), sandbox=FakeSandbox(), broker=None,
        model=CompletingModel(), verifier=verifier,
        config=LoopConfig(verify_cmd="pytest -q", max_rounds=3, max_steps=20),
    )
    escalations: list[Escalation] = []
    phases: list[str] = []
    async for ev in loop.run("写个 fix", "s"):
        if isinstance(ev, PhaseChange):
            phases.append(ev.phase)
        if isinstance(ev, Escalation):
            escalations.append(ev)

    assert not escalations, "用户级 passed 必走 break,不应触发 Escalation"
    assert phases[-1] == "report"
    assert verifier.calls == 1, "用户级 passed 应在第一次 verify 后 break,verifier 不应反复跑"




@pytest.mark.asyncio
async def test_loop_self_verified_does_not_capture_run_success(monkeypatch, tmp_path):
    """Internal documentation."""
    mem_dir = tmp_path / "memory"
    monkeypatch.setenv("ARGOS_MEMORY_DIR", str(mem_dir))
    monkeypatch.setenv("ARGOS_NO_MEMORY", "1")

    from argos.memory import auto as mem_auto
    captured: list[dict] = []
    orig_capture = mem_auto.capture_event

    def _spy_capture(event_type, **kw):
        captured.append({"type": event_type, **kw})
        return orig_capture(event_type, **kw)
    monkeypatch.setattr(mem_auto, "capture_event", _spy_capture)

    verifier = SelfPassedVerifier()
    loop = AgentLoop(
        store=FakeStore(), bus=EventBus(), sandbox=FakeSandbox(), broker=None,
        model=CompletingModel(), verifier=verifier,
        config=LoopConfig(verify_cmd="pytest -q", max_rounds=2, max_steps=20),
    )
    async for _ in loop.run("写个 fix", "s"):
        pass

    run_success = [c for c in captured if c.get("type") == "run_success"]
    assert run_success == [],\
        f"C2 修复后,self_verified 不得触发 run_success 写 memory,实际抓到 {run_success}"
    assert any(c.get("type") == "escalation_decision" for c in captured),\
        "升级路径应正常写 escalation_decision memory"


@pytest.mark.asyncio
async def test_loop_user_verified_captures_run_success(monkeypatch, tmp_path):
    """Internal documentation."""
    mem_dir = tmp_path / "memory"
    monkeypatch.setenv("ARGOS_MEMORY_DIR", str(mem_dir))
    monkeypatch.setenv("ARGOS_NO_MEMORY", "1")

    from argos.memory import auto as mem_auto
    captured: list[dict] = []
    orig_capture = mem_auto.capture_event

    def _spy_capture(event_type, **kw):
        captured.append({"type": event_type, **kw})
        return orig_capture(event_type, **kw)
    monkeypatch.setattr(mem_auto, "capture_event", _spy_capture)

    verifier = UserPassedVerifier()
    loop = AgentLoop(
        store=FakeStore(), bus=EventBus(), sandbox=FakeSandbox(), broker=None,
        model=WorkingThenCompletingModel(), verifier=verifier,
        config=LoopConfig(verify_cmd="pytest -q", max_rounds=5, max_steps=20),
    )
    async for _ in loop.run("写个 fix", "s"):
        pass

    run_success = [c for c in captured if c.get("type") == "run_success"]
    assert run_success, "用户级 passed + step>=5 应正常写 run_success(回归测试)"




def test_is_user_verified_is_single_source_of_truth():
    """Internal documentation."""
    user_passed = Verdict.passed("ok", "pytest -q", 1)
    self_passed = Verdict.passed_self("ok", "pytest -q", 1)
    failed = Verdict.failed("boom", "pytest -q", 1)
    unver = Verdict.unverifiable("can't tell", [], 1)

    truth_table = {
        "user_passed": user_passed.is_user_verified,
        "self_passed": self_passed.is_user_verified,
        "failed": failed.is_user_verified,
        "unverifiable": unver.is_user_verified,
    }
    assert truth_table == {
        "user_passed": True,
        "self_passed": False,
        "failed": False,
        "unverifiable": False,
    }, f"is_user_verified 真值表错位:{truth_table}"
    assert self_passed.status == "passed" and not self_passed.is_user_verified,\
        "防火墙核心不变量:status=='passed' + self_verified=True → is_user_verified 必须 False"
