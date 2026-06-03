"""Phase 3:AgentLoop CodeAct 主循环(FakeModel+FakeSandbox)。
抽代码块→exec→回灌→投事件;阶段门 plan→act→verify→report 不可跳。"""
from __future__ import annotations

import pytest

from argos_agent.core.loop import AgentLoop, LoopConfig, extract_code_block
from argos_agent.core.verify_gate import Verdict
from argos_agent.sandbox.backend import ExecResult
from argos_agent.tui.events import (
    CodeAction, CodeResult, PhaseChange, TokenDelta, VerifyVerdict,
)


def test_extract_code_block():
    txt = "先想想\n```python\nx = read_file('a.txt')\nprint(x)\n```\n结束"
    assert extract_code_block(txt) == "x = read_file('a.txt')\nprint(x)"
    assert extract_code_block("没有代码块") is None


class FakeModel:
    """按脚本逐 run 出 text。每次 stream 返回脚本的下一段。"""
    def __init__(self, scripts: list[str]):
        self._scripts = scripts
        self._i = 0

    async def stream(self, messages, *, system):
        text = self._scripts[min(self._i, len(self._scripts) - 1)]
        self._i += 1
        for ch in text:
            yield ch


class FakeSandbox:
    def __init__(self):
        self.spawned = False
        self.codes: list[str] = []
    def spawn(self, *, workspace, namespace):
        self.spawned = True
    def exec_code(self, code):
        self.codes.append(code)
        return ExecResult(stdout="ran ok", value_repr="", exc="")
    def close(self):
        pass


class FakeVerifier:
    """契约 §9 锁#1 canonical 签名: verify(verify_cmd, *, attempts=1) -> Verdict"""
    def verify(self, verify_cmd, *, attempts=1):
        return Verdict.passed(detail="[exit_code=0]", verify_cmd=verify_cmd, attempts=attempts)


class FakeStore:
    def __init__(self):
        self.events = []
    def append_event(self, sid, ev):
        self.events.append(ev)
    def append_message(self, sid, *, role, content, tool_calls_json="", token_count=0):
        return "m0"


def _loop(scripts, verify_cmd=None):
    from argos_agent.tui.events import EventBus
    return AgentLoop(
        store=FakeStore(), bus=EventBus(), sandbox=FakeSandbox(),
        broker=None, model=FakeModel(scripts), verifier=FakeVerifier(),
        config=LoopConfig(verify_cmd=verify_cmd, max_steps=5),
    )


@pytest.mark.asyncio
async def test_loop_runs_code_and_emits_events():
    # 第一段含代码块,第二段宣布完成(无代码块)。
    scripts = [
        "我来读文件\n```python\nwrite_file('a.txt','hi')\n```",
        "完成了。",
    ]
    loop = _loop(scripts)
    kinds = []
    async for ev in loop.run("写个文件", "sess1"):
        kinds.append(ev.kind)
    # 必含:phase_change(plan/act/.../report) + code_action + code_result
    assert "code_action" in kinds
    assert "code_result" in kinds
    assert "phase_change" in kinds


@pytest.mark.asyncio
async def test_phases_in_order_and_complete():
    scripts = ["```python\nwrite_file('a.txt','x')\n```", "完成。"]
    loop = _loop(scripts)
    phases = []
    async for ev in loop.run("g", "s"):
        if isinstance(ev, PhaseChange):
            phases.append(ev.phase)
    # 四阶段不可跳:plan 必在 act 之前,report 必在最后。
    assert phases[0] == "plan"
    assert "act" in phases
    assert phases[-1] == "report"
    assert phases.index("plan") < phases.index("act") < phases.index("report")


@pytest.mark.asyncio
async def test_verify_phase_emitted_before_verdict():
    """W1: PhaseChange("verify") 必须在 VerifyVerdict 之前。"""
    scripts = ["```python\nx=1\n```", "完成。"]
    loop = _loop(scripts, verify_cmd="echo ok")
    events = []
    async for ev in loop.run("g", "s"):
        events.append(ev)
    phase_changes = [e for e in events if isinstance(e, PhaseChange)]
    verdicts = [e for e in events if isinstance(e, VerifyVerdict)]
    verify_phase_idx = next(
        (i for i, e in enumerate(events) if isinstance(e, PhaseChange) and e.phase == "verify"), None
    )
    verdict_idx = next(
        (i for i, e in enumerate(events) if isinstance(e, VerifyVerdict)), None
    )
    # VerifyVerdict 存在时,PhaseChange("verify") 必须在它之前。
    if verdicts:
        assert verify_phase_idx is not None, "缺 PhaseChange('verify')"
        assert verify_phase_idx < verdict_idx, "PhaseChange('verify') 必须在 VerifyVerdict 之前(W1)"
