"""Internal documentation."""
from __future__ import annotations

import asyncio

import pytest


async def _drive_to_pending_then(gate, respond_kind: str):
    """Internal documentation."""
    for _ in range(300):
        await asyncio.sleep(0.01)
        pend = gate.pending()
        if pend:
            gate.respond(pend[0].call_id, respond_kind)
            return True
    return False


@pytest.mark.asyncio
async def test_threadsafe_bridge_approve():
    from argos.approval import ApprovalGate, ApprovalLevel
    gate = ApprovalGate(ApprovalLevel.CONFIRM)
    main_loop = asyncio.get_running_loop()

    def worker():
        fut = asyncio.run_coroutine_threadsafe(
            gate.request("run_command", {"command": "echo hi"},
                         description="echo hi", risk="low"),
            main_loop,
        )
        return fut.result(timeout=15)

    worker_task = asyncio.create_task(asyncio.to_thread(worker))
    assert await _drive_to_pending_then(gate, "once"), "请求从未挂起(桥没把 request 送上主循环?)"
    decision = await worker_task
    assert decision.approved is True
    assert decision.kind == "once"


@pytest.mark.asyncio
async def test_threadsafe_bridge_deny():
    from argos.approval import ApprovalGate, ApprovalLevel
    gate = ApprovalGate(ApprovalLevel.CONFIRM)
    main_loop = asyncio.get_running_loop()

    def worker():
        fut = asyncio.run_coroutine_threadsafe(
            gate.request("run_command", {"command": "echo hi"},
                         description="echo hi", risk="low"),
            main_loop,
        )
        return fut.result(timeout=15)

    worker_task = asyncio.create_task(asyncio.to_thread(worker))
    assert await _drive_to_pending_then(gate, "deny")
    decision = await worker_task
    assert decision.approved is False
    assert decision.kind == "deny"
