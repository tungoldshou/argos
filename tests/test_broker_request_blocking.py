"""同步桥交互审批:broker.request_blocking 把 request() 提交回 host_loop,工作线程阻塞等;
主循环 gate.respond 唤醒 → 完整 gating(egress+审批+执行+回执)生效。
host_loop 未设 → 回退 execute_sync(零回归)。"""
from __future__ import annotations

import asyncio

import pytest

from argos.approval import ApprovalGate, ApprovalLevel
from argos.sandbox.broker import CapabilityBroker
from argos.sandbox.egress import EgressPolicy
from argos.tools.receipts import ReceiptSigner


def _broker(level=ApprovalLevel.CONFIRM, workspace=None):
    gate = ApprovalGate(level=level)
    egress = EgressPolicy(llm_hosts=set(), search_hosts=set(), mcp_hosts=set())
    signer = ReceiptSigner(key=b"host-only-key")
    return CapabilityBroker(gate=gate, egress=egress, signer=signer, workspace=workspace)


async def _respond_first_pending(gate, kind: str) -> bool:
    for _ in range(300):
        await asyncio.sleep(0.01)
        pend = gate.pending()
        if pend:
            gate.respond(pend[0].call_id, kind)
            return True
    return False


@pytest.mark.asyncio
async def test_request_blocking_bridges_to_interactive_approval(monkeypatch):
    """host_loop 已设:request_blocking 在工作线程提交 request() 回主循环,主循环 respond 后放行执行。"""
    def fake_run(command, *, workspace=None):
        return ("ran:" + command, 0)
    monkeypatch.setattr("argos.tools.shell.run_command", fake_run)

    br = _broker(level=ApprovalLevel.CONFIRM)
    br.set_host_loop(asyncio.get_running_loop())

    worker = asyncio.create_task(
        asyncio.to_thread(br.request_blocking, "run_command", {"command": "echo hi"})
    )
    assert await _respond_first_pending(br.gate, "once"), "请求从未挂起(桥没把 request 送回主循环?)"
    value = await worker
    assert value == "ran:echo hi"                                   # 批准后真执行
    assert br.last_receipt is not None and br.last_receipt.action == "run_command"  # 回执签发


@pytest.mark.asyncio
async def test_request_blocking_denied_returns_refusal(monkeypatch):
    """拒绝 → 返回拒绝串、不执行、不签回执(无副作用)。"""
    def fake_run(command, *, workspace=None):
        return ("SHOULD-NOT-RUN", 0)
    monkeypatch.setattr("argos.tools.shell.run_command", fake_run)

    br = _broker(level=ApprovalLevel.CONFIRM)
    br.set_host_loop(asyncio.get_running_loop())

    worker = asyncio.create_task(
        asyncio.to_thread(br.request_blocking, "run_command", {"command": "echo hi"})
    )
    assert await _respond_first_pending(br.gate, "deny")
    value = await worker
    assert "拒绝" in str(value)
    assert "SHOULD-NOT-RUN" not in str(value)
    assert br.last_receipt is None


@pytest.mark.asyncio
async def test_request_blocking_force_confirms_run_command_under_auto(monkeypatch):
    """AUTO 档下 run_command 仍被 _FORCE_CONFIRM 经桥强制弹审批(不静默跑 shell)。"""
    def fake_run(command, *, workspace=None):
        return ("ran", 0)
    monkeypatch.setattr("argos.tools.shell.run_command", fake_run)

    br = _broker(level=ApprovalLevel.AUTO)
    br.set_host_loop(asyncio.get_running_loop())
    worker = asyncio.create_task(
        asyncio.to_thread(br.request_blocking, "run_command", {"command": "ls"})
    )
    assert await _respond_first_pending(br.gate, "once"), \
        "AUTO 档 run_command 未被 force-confirm(桥旁路了 _FORCE_CONFIRM?)"
    assert await worker == "ran"


def test_request_blocking_fallback_no_host_loop(monkeypatch):
    """host_loop 未设(headless/旧路径)→ 回退 execute_sync(无交互审批,零回归;仍签回执)。"""
    def fake_run(command, *, workspace=None):
        return ("ran:" + command, 0)
    monkeypatch.setattr("argos.tools.shell.run_command", fake_run)

    br = _broker(level=ApprovalLevel.AUTO)   # 无 host_loop
    value = br.request_blocking("run_command", {"command": "ls"})
    assert value == "ran:ls"
    assert br.last_receipt is not None
