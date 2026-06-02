"""fan-out —— asyncio.gather + copy_context() 自定义派发(承重墙)。

为什么不用 LangGraph Send:探针 /tmp/send_probe2.py 铁证 LangGraph 0.3.7 的 Send 默认
不复制 caller 的 ContextVar 到子任务(['A:DEFAULT','B:DEFAULT','C:DEFAULT']),
spec §4.3 红线兑现必须手动 asyncio.Task(coro, context=copy_context())。
本模块是该承重墙接缝的实现,生产路径 server._run_stream 设的 ctx 不会自动跨 fan-out
传给 worker,所以 fan-out 内部每 worker 协程必须自己 set_context(在 worker._run_one_task_impl
第一步),且调用方需用 copy_context() 显式复制父 ctx(虽父 ctx 没 per-task ws,但未来扩展
需要保留父 ctx 的比如 approval_gate / config.LLM_KEY 等)。
"""
from __future__ import annotations

import asyncio
import contextvars
import logging
from typing import Iterable, List, Tuple

from . import worker
from .plan_schema import PlanTask

log = logging.getLogger(__name__)


async def fan_out(
    plan_tasks: Iterable[Tuple[PlanTask, "Path", "Path"]],
    session_id: str,
) -> List[worker.WorkerResult]:
    """对每个 (task, ws, vd) 派一个 worker task,asyncio.gather 全收。

    调用方传每个 task 的隔离路径(由 orchestrator 调 isolation.acquire_* 计算);
    fan-out 只负责调度,不动 isolation。
    """
    tasks = []
    for t, ws, vd in plan_tasks:
        # 关键:copy_context() 复制当前 task 的 ctx(父 ctx 里有 approval / future hooks),
        # 派生 asyncio.Task 时显式传 context=ctx(承重墙接缝)。
        # 即便父 ctx 没 per-task 状态(per-task ws/vd 在 worker 内 set),也保留父 ctx 的
        # approval_gate 等跨 fan-out 不变量。
        ctx = contextvars.copy_context()
        coro = worker.run_one_task(t, ws, vd)
        tasks.append(asyncio.create_task(coro, context=ctx))
    results = await asyncio.gather(*tasks, return_exceptions=True)
    out: List[worker.WorkerResult] = []
    for t, r in zip([t for t, _, _ in plan_tasks], results):
        if isinstance(r, Exception):
            out.append(worker.WorkerResult(
                task_id=t.task_id, verdict="failed", error=f"{type(r).__name__}: {r!r}",
            ))
        else:
            out.append(r)
    return out
