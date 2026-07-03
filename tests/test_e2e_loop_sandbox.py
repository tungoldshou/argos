from __future__ import annotations

import os
from pathlib import Path

import pytest

from argos.approval import ApprovalGate, ApprovalLevel
from argos.core.loop import AgentLoop, LoopConfig
from argos.core.verify_gate import Verdict, Verifier
from argos.sandbox.broker import CapabilityBroker
from argos.sandbox.egress import EgressPolicy
from argos.sandbox.executor import select_backend
from argos.tools.receipts import ReceiptSigner
from argos.tui.events import CodeResult, EventBus, PhaseChange


class ScriptModel:
    def __init__(self, scripts: list[str]):
        self._s = scripts
        self._i = 0

    async def stream(self, messages, *, system, system_dynamic=None):
        text = self._s[min(self._i, len(self._s) - 1)]
        self._i += 1
        for ch in text:
            yield ch


class PassVerifier:
    def verify(self, verify_cmd, *, attempts=1):
        return Verdict.passed(detail="[exit_code=0]", verify_cmd=verify_cmd, attempts=attempts)


class MemStore:
    def __init__(self): self.events = []
    def append_event(self, sid, ev): self.events.append(ev)
    def append_message(self, sid, **kw): return "m0"


@pytest.mark.asyncio
async def test_codeact_writes_file_in_real_sandbox(tmp_path, requires_sandbox):
    os.environ["ARGOS_WORKSPACE"] = str(tmp_path)

    gate = ApprovalGate(level=ApprovalLevel.AUTO)
    egress = EgressPolicy(llm_hosts=set(), search_hosts=set(), mcp_hosts=set())
    signer = ReceiptSigner(key=b"test-e2e-key")
    broker = CapabilityBroker(gate=gate, egress=egress, signer=signer)

    def broker_handler(action, args):
        value, exit_code = broker._execute(action, args)
        return value

    ex = select_backend()(broker_handler=broker_handler)

    scripts = [
        "写文件\n```python\nwrite_file('e2e_out.txt', 'sandbox wrote this')\n```",
        "完成。",
    ]

    loop = AgentLoop(
        store=MemStore(),
        bus=EventBus(),
        sandbox=ex,
        broker=broker,
        model=ScriptModel(scripts),
        verifier=PassVerifier(),
        config=LoopConfig(verify_cmd=None, max_steps=4),
        workspace=tmp_path,
        verify_dir=tmp_path / "verify",
    )

    results: list[CodeResult] = []
    phases: list[str] = []
    async for ev in loop.run("写文件到沙箱", "e2e-sess"):
        if isinstance(ev, CodeResult):
            results.append(ev)
        if isinstance(ev, PhaseChange):
            phases.append(ev.phase)

    assert results, "没有 CodeResult 事件 —— loop 没有执行代码"

    assert any(r.ok for r in results), f"所有 CodeResult 都失败: {[r.exc for r in results]}"

    target = tmp_path / "e2e_out.txt"
    assert target.exists(), (
        f"文件未落盘 tmp_path/{target.name}。"
        f" workspace={tmp_path}, results={results}"
    )
    content = target.read_text()
    assert content == "sandbox wrote this", f"文件内容不对: {content!r}"

    assert "plan" in phases
    assert "act" in phases
    assert "report" in phases
