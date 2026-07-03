from __future__ import annotations

import pytest

from argos.core.loop import AgentLoop, LoopConfig
from argos.core.verify_gate import Verdict
from argos.sandbox.backend import ExecResult
from argos.tui.events import EventBus, VerifyVerdict
from tests.test_loop_codeact import FakeStore


def test_tool_names_indicate_file_mutation_without_source_string_scan():
    from argos.core.loop import _tool_names_indicate_mutation

    assert _tool_names_indicate_mutation(["write_file"]) is True
    assert _tool_names_indicate_mutation(["edit_file"]) is True
    assert _tool_names_indicate_mutation(["read_file", "run_command"]) is False


class _ProposeSandbox:
    def __init__(self, on_propose): self._on_propose = on_propose
    def spawn(self, *, workspace, namespace, allow_workflow=True, read_only=False): pass
    def exec_code(self, code):
        if "propose_verify" in code:
            import re
            m = re.search(r"propose_verify\(['\"](.+?)['\"]\)", code)
            if m: self._on_propose(m.group(1))
        return ExecResult(stdout="ok", value_repr="", exc="")
    def close(self): pass


class _RecordingVerifier:
    def __init__(self): self.ran_cmd = None
    def verify(self, verify_cmd, *, attempts=1):
        self.ran_cmd = verify_cmd
        return Verdict.passed(detail="[exit_code=0]", verify_cmd=verify_cmd, attempts=attempts)


def test_propose_verify_rejects_trivial_noop_commands():
    from tests.test_loop_codeact import FakeModel
    loop = AgentLoop(store=FakeStore(), bus=EventBus(),
                     sandbox=_ProposeSandbox(lambda c: None), broker=None,
                     model=FakeModel([]), verifier=_RecordingVerifier(),
                     config=LoopConfig(verify_cmd=None))
    for fake in ["echo ok", "true", "ls", "pwd", "cat x.txt", ":", "printf hi"]:
        loop._verify_cmd = None
        loop._on_propose_verify(fake)
        assert loop._verify_cmd is None, f"{fake!r} 不该被当验证命令登记(伪验证)"
    loop._verify_cmd = None
    loop._on_propose_verify("pytest tests/test_x.py")
    assert loop._verify_cmd == "pytest tests/test_x.py"


class _RecModel:
    def __init__(self, scripts): self._s = scripts; self._i = 0; self.seen = []
    async def stream(self, messages, *, system, system_dynamic=None):
        self.seen.append([m.get("content", "") for m in messages])
        t = self._s[min(self._i, len(self._s) - 1)]; self._i += 1
        for ch in t:
            yield ch


@pytest.mark.asyncio
async def test_h2_nudges_to_verify_when_code_changed_without_verify_cmd():
    from argos.core.verify_gate import Verifier
    model = _RecModel([
        "```python\nwrite_file('x.py', 'x=1')\n```",
        "完成。",
        "完成。",
    ])
    loop = AgentLoop(store=FakeStore(), bus=EventBus(), sandbox=_ProposeSandbox(lambda c: None),
                     broker=None, model=model, verifier=Verifier(),
                     config=LoopConfig(verify_cmd=None, max_steps=8))
    async for _ in loop.run("改个文件", "s"):
        pass
    flat = "\n".join(msg for call in model.seen for msg in call)
    assert "propose_verify" in flat and "没有声明验证" in flat, "改了代码却没声明验证 → 应回灌一次催促"
    assert flat.count("没有声明验证") == 1


@pytest.mark.asyncio
async def test_h2_no_nudge_for_readonly_task():
    from argos.core.verify_gate import Verifier
    model = _RecModel([
        "```python\nprint(read_file('x.py'))\n```",
        "完成。",
    ])
    loop = AgentLoop(store=FakeStore(), bus=EventBus(), sandbox=_ProposeSandbox(lambda c: None),
                     broker=None, model=model, verifier=Verifier(),
                     config=LoopConfig(verify_cmd=None, max_steps=8))
    async for _ in loop.run("看看 x.py", "s"):
        pass
    flat = "\n".join(msg for call in model.seen for msg in call)
    assert "没有声明验证" not in flat, "纯读任务不该被催验证"


@pytest.mark.asyncio
async def test_fake_verify_command_does_not_produce_false_green():
    from tests.test_loop_codeact import FakeModel
    from argos.core.verify_gate import Verifier
    model = FakeModel([
        "```python\npropose_verify('echo ok')\nwrite_file('x.py','x=1')\n```",
        "完成。",
    ])
    loop = AgentLoop(store=FakeStore(), bus=EventBus(), sandbox=_ProposeSandbox(lambda c: None),
                     broker=None, model=model, verifier=Verifier(), config=LoopConfig(verify_cmd=None))
    verdicts = []
    async for ev in loop.run("g", "s"):
        if isinstance(ev, VerifyVerdict):
            verdicts.append(ev.verdict)
    assert verdicts, "应有 verify 裁决"
    assert verdicts[-1].status != "passed", "echo ok 绝不得产生假绿 passed"
    assert verdicts[-1].status == "unverifiable"


@pytest.mark.asyncio
async def test_agent_proposed_cmd_is_run_by_harness():
    verifier = _RecordingVerifier()
    proposed = {}
    sandbox = _ProposeSandbox(lambda cmd: proposed.update(cmd=cmd))
    from tests.test_loop_codeact import FakeModel
    model = FakeModel([
        "```python\npropose_verify('pytest tests/test_x.py')\nwrite_file('x.py','...')\n```",
        "完成。",
    ])
    loop = AgentLoop(store=FakeStore(), bus=EventBus(), sandbox=sandbox, broker=None,
                     model=model, verifier=verifier, config=LoopConfig(verify_cmd=None))
    verdicts = []
    async for ev in loop.run("g", "s"):
        if isinstance(ev, VerifyVerdict):
            verdicts.append(ev.verdict)
    assert verifier.ran_cmd == "pytest tests/test_x.py", "harness 必须独立跑 agent 提议的命令"
    assert verdicts and verdicts[-1].status == "passed"
