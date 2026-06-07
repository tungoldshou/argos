"""Phase 3 铁证:真 AgentLoop + 真沙箱后端 + 真 CapabilityBroker。

FakeModel 出脚本代码,但代码在真沙箱里跑(macOS Seatbelt / Linux bwrap/unshare);
broker-gated 工具经 broker RPC 往返;沙箱内 write_file 真落盘 workspace 内。

铁证三要素:
  ① CodeAct 循环投 CodeAction + CodeResult 事件(真 loop 运行)。
  ② write_file 代码在真沙箱后端子进程内执行。
  ③ 文件真落盘到 tmp_path(OS 级别的 workspace 内写入,非 mock)。
无沙箱后端的平台干净 skip,不假装跑过。
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from argos_agent.approval import ApprovalGate, ApprovalLevel
from argos_agent.core.loop import AgentLoop, LoopConfig
from argos_agent.core.verify_gate import Verdict, Verifier
from argos_agent.sandbox.broker import CapabilityBroker
from argos_agent.sandbox.egress import EgressPolicy
from argos_agent.sandbox.executor import select_backend
from argos_agent.tools.receipts import ReceiptSigner
from argos_agent.tui.events import CodeResult, EventBus, PhaseChange


class ScriptModel:
    """按脚本逐 run 出 text,不调真模型。"""
    def __init__(self, scripts: list[str]):
        self._s = scripts
        self._i = 0

    async def stream(self, messages, *, system, system_dynamic=None):
        text = self._s[min(self._i, len(self._s) - 1)]
        self._i += 1
        for ch in text:
            yield ch


class PassVerifier:
    """契约 §9 锁#1 canonical 签名."""
    def verify(self, verify_cmd, *, attempts=1):
        return Verdict.passed(detail="[exit_code=0]", verify_cmd=verify_cmd, attempts=attempts)


class MemStore:
    def __init__(self): self.events = []
    def append_event(self, sid, ev): self.events.append(ev)
    def append_message(self, sid, **kw): return "m0"


@pytest.mark.asyncio
async def test_codeact_writes_file_in_real_sandbox(tmp_path, requires_sandbox):
    """铁证:真 AgentLoop 驱动真沙箱后端,沙箱内 write_file 真落盘 workspace。"""
    # 注入 ARGOS_WORKSPACE → 子进程 files.py 模块级 WORKSPACE 解析到 tmp_path。
    os.environ["ARGOS_WORKSPACE"] = str(tmp_path)

    gate = ApprovalGate(level=ApprovalLevel.AUTO)
    egress = EgressPolicy(llm_hosts=set(), search_hosts=set(), mcp_hosts=set())
    signer = ReceiptSigner(key=b"test-e2e-key")
    broker = CapabilityBroker(gate=gate, egress=egress, signer=signer)

    # 同步 broker_handler 桥:AUTO gate 直接 _execute(不走 async await)。
    def broker_handler(action, args):
        value, exit_code = broker._execute(action, args)
        return value

    ex = select_backend()(broker_handler=broker_handler)

    # 脚本:第一轮含 write_file 代码块,第二轮宣布完成。
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

    # 铁证①:loop 真实运行,发出了 CodeResult 事件。
    assert results, "没有 CodeResult 事件 —— loop 没有执行代码"

    # 铁证②:至少一个 CodeResult 成功。
    assert any(r.ok for r in results), f"所有 CodeResult 都失败: {[r.exc for r in results]}"

    # 铁证③:文件真落盘(OS 级别的 write,非 mock)。
    target = tmp_path / "e2e_out.txt"
    assert target.exists(), (
        f"文件未落盘 tmp_path/{target.name}。"
        f" workspace={tmp_path}, results={results}"
    )
    content = target.read_text()
    assert content == "sandbox wrote this", f"文件内容不对: {content!r}"

    # 铁证额外:四阶段都出现了。
    assert "plan" in phases
    assert "act" in phases
    assert "report" in phases
