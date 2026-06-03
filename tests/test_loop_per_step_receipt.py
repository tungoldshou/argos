"""I2 铁证:ToolReceipt 只在【本步新签了 Receipt】时投,不重投陈旧回执。

旧 bug:loop 每个 code-action 后读 broker.last_receipt,只要非 None 就投 ToolReceipt;
broker.last_receipt 从不清空 → 第二步(被拒/无副作用)会把第一步的成功回执张冠李戴重投。
修复:broker.take_receipt() 返回并清空,loop 只在拿到新回执时投事件。
"""
from __future__ import annotations

import pytest

from argos_agent.core.loop import AgentLoop, LoopConfig
from argos_agent.core.verify_gate import Verdict
from argos_agent.sandbox.backend import ExecResult
from argos_agent.tools.receipts import ReceiptSigner
from argos_agent.tui.events import EventBus, ToolReceipt


class FakeModel:
    def __init__(self, scripts):
        self._s = scripts
        self._i = 0

    async def stream(self, messages, *, system):
        text = self._s[min(self._i, len(self._s) - 1)]
        self._i += 1
        for ch in text:
            yield ch


class FakeSandbox:
    def __init__(self):
        self.codes = []

    def spawn(self, *, workspace, namespace):
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
    """模拟 CapabilityBroker 的 last_receipt / take_receipt 契约:
    第一次代码动作签一个 Receipt;之后(被拒/无副作用)不再签。"""

    def __init__(self):
        self._signer = ReceiptSigner(key=b"i2-test")
        self.last_receipt = None
        self._signed_once = False

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
            # 第一步代码里含 'broker' 标记 → 模拟一次成功的 broker 动作签了回执。
            if "DO_BROKER" in code and not broker._signed_once:
                broker.sign_step_one()
                broker._signed_once = True
            return ExecResult(stdout="ran", value_repr="", exc="")

    scripts = [
        "第一步\n```python\nx = 'DO_BROKER'\n```",   # 触发签回执
        "第二步\n```python\ny = 1\n```",             # 无新回执
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
    """全程无 broker 动作 → 0 个 ToolReceipt(陈旧回执不会被凭空重投)。"""
    broker = StepBroker()  # 从不 sign
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
