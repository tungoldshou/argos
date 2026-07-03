"""Internal documentation."""
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
    """Internal documentation."""
    def fake_run(command, *, workspace=None, allow_network=False):
        return ("ran:" + command, 0)
    monkeypatch.setattr("argos.tools.shell.run_command", fake_run)

    br = _broker(level=ApprovalLevel.CONFIRM)
    br.set_host_loop(asyncio.get_running_loop())

    worker = asyncio.create_task(
        asyncio.to_thread(br.request_blocking, "run_command", {"command": "echo hi"})
    )
    assert await _respond_first_pending(br.gate, "once"), "请求从未挂起(桥没把 request 送回主循环?)"
    value = await worker
    assert value == "ran:echo hi"
    assert br.last_receipt is not None and br.last_receipt.action == "run_command"


@pytest.mark.asyncio
async def test_request_blocking_denied_returns_refusal(monkeypatch):
    """Internal documentation."""
    def fake_run(command, *, workspace=None, allow_network=False):
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
async def test_request_blocking_run_command_auto_runs_under_yolo(monkeypatch):
    """Internal documentation."""
    def fake_run(command, *, workspace=None, allow_network=False):
        return ("ran", 0)
    monkeypatch.setattr("argos.tools.shell.run_command", fake_run)

    br = _broker(level=ApprovalLevel.AUTO)
    br.set_host_loop(asyncio.get_running_loop())
    value = await asyncio.create_task(
        asyncio.to_thread(br.request_blocking, "run_command", {"command": "ls"})
    )
    assert value == "ran"
    assert br.gate.pending() == [], "YOLO 下经桥的 run_command 不应挂起审批"


def test_request_blocking_fallback_no_host_loop(monkeypatch):
    """Internal documentation."""
    def fake_run(command, *, workspace=None, allow_network=False):
        return ("ran:" + command, 0)
    monkeypatch.setattr("argos.tools.shell.run_command", fake_run)

    br = _broker(level=ApprovalLevel.AUTO)
    value = br.request_blocking("run_command", {"command": "ls"})
    assert value == "ran:ls"
    assert br.last_receipt is not None
