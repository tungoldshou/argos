"""Spike(地面真值):证明 to_thread 工作线程里 run_coroutine_threadsafe(gate.request)
能被主循环上的 gate.respond 跨 loop 唤醒、无死锁 —— 同步桥交互审批的核心机制。

旧教训(argos-approval-gate-2026-06-02):跨 loop future 必须用 future 自己的 loop 唤醒;
gate 已用 _Pending.loop + call_soon_threadsafe 做到。本 spike 在真实 ApprovalGate 上验证。
"""
from __future__ import annotations

import asyncio

import pytest


async def _drive_to_pending_then(gate, respond_kind: str):
    """主循环空闲:轮询挂起请求,出现即 respond(respond_kind);返回是否真 responded。"""
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
        # 工作线程:把 gate.request 提交回主循环,阻塞等结果(模拟 broker_handler 跨线程桥)
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
