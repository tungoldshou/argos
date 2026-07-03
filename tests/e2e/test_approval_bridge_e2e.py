"""Internal documentation."""
from __future__ import annotations

import asyncio

import pytest

from argos.approval import ApprovalLevel
from argos.tui.events import CodeResult, ToolReceipt

_SCRIPTS = [
    "跑命令\n```python\nprint(run_command('echo bridged'))\n```",
    "完成。",
]


@pytest.mark.slow
@pytest.mark.asyncio
async def test_run_command_through_bridge_approves_and_executes(build_real_loop):
    """Internal documentation."""
    loop = build_real_loop(_SCRIPTS, level=ApprovalLevel.CONFIRM, gated=True)
    gate = loop._broker.gate

    approved: list[str] = []

    async def responder():
        while True:
            await asyncio.sleep(0.01)
            for p in list(gate.pending()):
                if gate.respond(p.call_id, "once"):
                    approved.append(p.call_id)

    rt = asyncio.create_task(responder())
    receipts: list[ToolReceipt] = []
    results: list[CodeResult] = []
    try:
        async for ev in loop.run("跑命令", "bridge-approve"):
            if isinstance(ev, ToolReceipt):
                receipts.append(ev)
            elif isinstance(ev, CodeResult):
                results.append(ev)
    finally:
        rt.cancel()

    assert approved, "审批闸从未收到挂起请求 —— 桥没把 request 送回主循环(exec_code 没让出事件循环?)"
    assert any("bridged" in (r.stdout or "") for r in results),\
        f"run_command 输出未回灌(被拒了?): {[r.stdout for r in results]}"
    assert any(getattr(r.receipt, "action", "") == "run_command" for r in receipts),\
        "批准后未投 run_command 的 ToolReceipt(回执链没在桥路径生效)"


@pytest.mark.slow
@pytest.mark.asyncio
async def test_cancel_mid_approval_settles_orphan(build_real_loop):
    """Internal documentation."""
    loop = build_real_loop(_SCRIPTS, level=ApprovalLevel.CONFIRM, gated=True)
    gate = loop._broker.gate

    async def drive():
        async for _ev in loop.run("跑命令", "bridge-cancel"):
            pass

    task = asyncio.create_task(drive())
    saw_pending = False
    for _ in range(500):
        await asyncio.sleep(0.01)
        if gate.pending():
            saw_pending = True
            break
    assert saw_pending, "无 responder 时 run_command 应挂起审批,却没出现挂起"

    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert gate.pending() == [], "cancel 后孤儿审批未被 cancel_all 清空(bug #2 回归)"
