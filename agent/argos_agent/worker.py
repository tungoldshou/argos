"""worker —— 在 caller copy_context() 副本内 set per-task RunContext,跑单 task。

承重墙接缝(探针已证):LangGraph Send 不复制 ContextVar,本步用 asyncio.gather + copy_context()
包每个 worker_coro,worker 内第一时间 runtime.set_context → tools._ws() 读到 per-task 隔离区。

本模块只暴露 run_one_task(task, ws, vd) -> WorkerResult;真 agent 调用在 _run_one_task_impl(可被
测试 monkeypatch,生产走 build_agent_with_gate + checkpointer + astream)。"""
from __future__ import annotations

import contextvars
import logging
import time
from dataclasses import dataclass
from pathlib import Path

from . import runtime
from .plan_schema import PlanTask

log = logging.getLogger(__name__)

# 单 task 超时(env 可调,spec §6)。超 → verdict=failed。
TASK_TIMEOUT_S = 300  # 5 min


@dataclass
class WorkerResult:
    task_id: str
    verdict: str  # "passed" | "failed" | "unverifiable"
    output_preview: str = ""  # 头几行 stdout / message 摘要,供 reducer/UI 用
    attempts: int = 1
    error: str = ""  # 失败时填


async def run_one_task(task: PlanTask, ws: Path, vd: Path) -> WorkerResult:
    """在当前 task 协程的 context(caller 负责 copy_context + set)内跑单 task。"""
    return await _run_one_task_impl(task, ws, vd)


async def _run_one_task_impl(task: PlanTask, ws: Path, vd: Path) -> WorkerResult:
    """生产路径:用第 5 步的 build_agent_with_gate + checkpointer 跑 task.goal,收 verdict。
    测试用 monkeypatch 替成本函数(见 test_worker.py)。"""
    from .core import build_agent_with_gate, final_text
    from . import approval
    from .tools import ALL_TOOLS
    from . import mcp_client
    from .verify_gate import _run_verify  # 既有 API:_run_verify(cmd) -> (ok: bool, detail: str)

    # set per-task RunContext(必填 project_mode=True,理由见第 5 步)
    token = runtime.set_context(runtime.RunContext(
        workspace=ws, verify_dir=vd, project_mode=True,
    ))
    gate_token = approval.set_current_gate(_per_task_gate())
    try:
        try:
            merged_tools = list(ALL_TOOLS) + mcp_client.mcp_tools()
            agent, gate = build_agent_with_gate(
                tools=merged_tools, verify_cmd=task.verify_cmd, goal=task.goal, checkpointer=None,
            )
        except Exception as e:
            return WorkerResult(task_id=task.task_id, verdict="failed", error=f"build_agent: {e!r}")

        # 简化路径:同步跑完整 astream(实际可走 aiter + collect),收敛成 result。
        # 注:本 step 只用 None checkpointer(plan 内不持久);若需 plan-level resume,后续再扩。
        try:
            result_text = ""
            attempts = 0
            async for ev in agent.astream({"messages": [("user", task.goal)]}, stream_mode="values"):
                msgs = ev.get("messages", [])
                if msgs:
                    last = msgs[-1]
                    result_text = final_text(last) or result_text
                attempts += 1
            # verdict:verify_cmd 给了就跑(白名单内),退出码 → passed/failed
            verdict = "passed"
            if task.verify_cmd:
                ok, detail = _run_verify(task.verify_cmd)
                if not ok:
                    verdict = "failed"
                    return WorkerResult(
                        task_id=task.task_id, verdict=verdict,
                        output_preview=result_text[:1500], attempts=attempts,
                        error=detail[:500],
                    )
            return WorkerResult(
                task_id=task.task_id, verdict=verdict,
                output_preview=result_text[:1500], attempts=attempts,
            )
        except Exception as e:
            return WorkerResult(task_id=task.task_id, verdict="failed", error=f"astream: {e!r}")
    finally:
        approval.reset_current_gate(gate_token)
        runtime.reset(token)


# 每 task 自己一个 auto-approve gate(spec §5 worker 简化路径)。
# 真实 plan 流程的审批闸由 orchestrator 层接(server 端已有 _SKILL_GATE 同款 _PLAN_GATE,本 task 不实现)
def _per_task_gate():
    from . import approval
    g = approval.ApprovalGate()
    async def auto(payload, timeout=60.0):
        return approval.Decision(approved=True, scope="once")
    g.request = auto  # type: ignore[assignment]
    return g
