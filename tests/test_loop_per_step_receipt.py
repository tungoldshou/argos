from __future__ import annotations

import pytest

from argos.core.loop import AgentLoop, LoopConfig
from argos.core.verify_gate import Verdict
from argos.sandbox.backend import ExecResult
from argos.tools.receipts import ReceiptSigner
from argos.tui.events import EventBus, ToolReceipt


class FakeModel:
    def __init__(self, scripts):
        self._s = scripts
        self._i = 0

    async def stream(self, messages, *, system, system_dynamic=None):
        text = self._s[min(self._i, len(self._s) - 1)]
        self._i += 1
        for ch in text:
            yield ch


class FakeSandbox:
    def __init__(self):
        self.codes = []

    def spawn(self, *, workspace, namespace, allow_workflow=True, read_only=False):
        pass

    def exec_code(self, code):
        self.codes.append(code)
        return ExecResult(stdout="ran", value_repr="", exc="")

    def close(self):
        pass


class FakeVerifier:
    def verify(self, verify_cmd, *, attempts=1):
        return Verdict.passed(detail="[exit_code=0]", verify_cmd=verify_cmd, attempts=attempts)


class FakeStore:
    def __init__(self):
        self.events = []

    def append_event(self, sid, ev):
        self.events.append(ev)

    def append_message(self, sid, **kw):
        return "m0"


class StepBroker:

    def __init__(self):
        self._signer = ReceiptSigner(key=b"i2-test")
        self.last_receipt = None
        self._signed_once = False

    @property
    def signer(self):
        return self._signer

    def sign_step_one(self):
        self.last_receipt = self._signer.sign(
            action="run_command", args={"command": "echo hi"}, result="hi", exit_code=0,
        )

    def take_receipt(self):
        rec = self.last_receipt
        self.last_receipt = None
        return rec


@pytest.mark.asyncio
async def test_exactly_one_receipt_across_two_code_actions():
    broker = StepBroker()

    class SignOnSpawnSandbox(FakeSandbox):
        def exec_code(self, code):
            if "DO_BROKER" in code and not broker._signed_once:
                broker.sign_step_one()
                broker._signed_once = True
            return ExecResult(stdout="ran", value_repr="", exc="")

    scripts = [
        "第一步\n```python\nx = 'DO_BROKER'\n```",
        "第二步\n```python\ny = 1\n```",
        "完成。",
    ]
    loop = AgentLoop(
        store=FakeStore(), bus=EventBus(), sandbox=SignOnSpawnSandbox(),
        broker=broker, model=FakeModel(scripts), verifier=FakeVerifier(),
        config=LoopConfig(verify_cmd=None, max_steps=6),
    )
    receipts = []
    async for ev in loop.run("g", "s"):
        if isinstance(ev, ToolReceipt):
            receipts.append(ev)

    assert len(receipts) == 1, f"应恰好 1 个 ToolReceipt(仅第一步新签),实得 {len(receipts)}"
    assert receipts[0].receipt.action == "run_command"


@pytest.mark.asyncio
async def test_no_receipt_when_no_broker_action():
    broker = StepBroker()
    scripts = [
        "```python\na = 1\n```",
        "```python\nb = 2\n```",
        "完成。",
    ]
    loop = AgentLoop(
        store=FakeStore(), bus=EventBus(), sandbox=FakeSandbox(),
        broker=broker, model=FakeModel(scripts), verifier=FakeVerifier(),
        config=LoopConfig(verify_cmd=None, max_steps=6),
    )
    receipts = [ev for ev in [e async for e in loop.run("g", "s")] if isinstance(ev, ToolReceipt)]
    assert receipts == []
