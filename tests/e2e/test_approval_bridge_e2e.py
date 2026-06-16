"""E2E 铁证:沙箱工具调用经【真 executor → broker_call → request_blocking 桥 → 交互审批】。

build_real_loop(gated=True) 把 broker_handler 换成生产 request_blocking;loop.run() 自动注入
host_loop。这里跑真沙箱子进程,断言 run_command 经审批闸放行后真执行(approve)、cancel 中途
断在审批上时 run() finally 的 cancel_all 立即清空孤儿挂起(不泄漏到 60s 超时)。

无沙箱后端的平台 requires_sandbox 干净 skip。
"""
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
    """approve:run_command 经 request_blocking 桥挂起审批 → respond once → 真执行 + 投回执。"""
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
    assert any("bridged" in (r.stdout or "") for r in results), \
        f"run_command 输出未回灌(被拒了?): {[r.stdout for r in results]}"
    assert any(getattr(r.receipt, "action", "") == "run_command" for r in receipts), \
        "批准后未投 run_command 的 ToolReceipt(回执链没在桥路径生效)"


@pytest.mark.slow
@pytest.mark.asyncio
async def test_cancel_mid_approval_settles_orphan(build_real_loop):
    """cancel 中途断在审批上 → run() finally 的 cancel_all 立即清空孤儿挂起(防泄漏到 60s 超时)。"""
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

    # run() finally 的 cancel_all 同步清空 _pending;否则孤儿 request() 会 pending 到 60s 超时。
    assert gate.pending() == [], "cancel 后孤儿审批未被 cancel_all 清空(bug #2 回归)"
