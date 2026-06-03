"""reducer —— 纯函数,看 N 个 worker_result 决定终态 or "补"动作。

决策树:
  - 全 pass  → PlanReport(failed=0)
  - 部分 fail & replan_rounds < MAX → Replan(failed_tasks)  // orchestrator 再调一次 planner
  - 全 fail or 补轮用尽  → PlanReport(failed=K)
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List

from .plan_schema import PlanTask
from .worker import WorkerResult

# spec §6:补轮上限 2(cost 翻倍仍败则 escalate,不死循环)
MAX_REPLAN_ROUNDS = 2


@dataclass
class PlanReport:
    split: int
    succeeded: int
    failed: int
    replan_rounds: int
    task_results: List[WorkerResult] = field(default_factory=list)


@dataclass
class Replan:
    failed_tasks: List[WorkerResult]
    replan_rounds_used: int


def reduce(
    plan: List[PlanTask],
    results: List[WorkerResult],
    replan_rounds: int,
) -> object:  # PlanReport | Replan
    """纯函数,无副作用。plan 与 results 一一对应(按 task_id 配对)。"""
    failed = [r for r in results if r.verdict != "passed"]
    succeeded = len(results) - len(failed)
    if not failed:
        return PlanReport(
            split=len(plan), succeeded=succeeded, failed=0,
            replan_rounds=replan_rounds, task_results=results,
        )
    if replan_rounds < MAX_REPLAN_ROUNDS:
        return Replan(failed_tasks=failed, replan_rounds_used=replan_rounds)
    return PlanReport(
        split=len(plan), succeeded=succeeded, failed=len(failed),
        replan_rounds=replan_rounds, task_results=results,
    )
