"""reducer 测试 —— 纯函数,看 N 个 worker_result 决定终态 or "补"动作。"""
import pytest

from argos_agent import reducer
from argos_agent.plan_schema import PlanTask
from argos_agent.worker import WorkerResult


def _plan(n):
    return [PlanTask(goal=f"t{i}", verify_cmd="x") for i in range(n)]


def test_reducer_all_pass_returns_plan_report():
    plan = _plan(3)
    results = [WorkerResult(task_id=t.task_id, verdict="passed", output_preview="ok") for t in plan]
    decision = reducer.reduce(plan, results, replan_rounds=0)
    assert isinstance(decision, reducer.PlanReport)
    assert decision.split == 3 and decision.succeeded == 3 and decision.failed == 0
    assert decision.replan_rounds == 0


def test_reducer_partial_fail_returns_replan_when_rounds_left():
    plan = _plan(3)
    results = [
        WorkerResult(task_id=plan[0].task_id, verdict="passed", output_preview="ok"),
        WorkerResult(task_id=plan[1].task_id, verdict="failed", error="boom", output_preview=""),
        WorkerResult(task_id=plan[2].task_id, verdict="passed", output_preview="ok"),
    ]
    decision = reducer.reduce(plan, results, replan_rounds=0)
    assert isinstance(decision, reducer.Replan)
    assert len(decision.failed_tasks) == 1
    assert decision.failed_tasks[0].task_id == plan[1].task_id
    assert decision.replan_rounds_used == 0


def test_reducer_replan_exhausted_returns_plan_report_with_failed():
    plan = _plan(3)
    results = [WorkerResult(task_id=t.task_id, verdict="failed", error="x", output_preview="") for t in plan]
    decision = reducer.reduce(plan, results, replan_rounds=reducer.MAX_REPLAN_ROUNDS)
    assert isinstance(decision, reducer.PlanReport)
    assert decision.split == 3 and decision.succeeded == 0 and decision.failed == 3


def test_reducer_increments_replan_rounds():
    plan = _plan(2)
    results = [WorkerResult(task_id=t.task_id, verdict="failed", error="x", output_preview="") for t in plan]
    d1 = reducer.reduce(plan, results, replan_rounds=0)
    assert isinstance(d1, reducer.Replan) and d1.replan_rounds_used == 0
    d2 = reducer.reduce(plan, results, replan_rounds=1)
    assert isinstance(d2, reducer.Replan) and d2.replan_rounds_used == 1
    d3 = reducer.reduce(plan, results, replan_rounds=2)
    assert isinstance(d3, reducer.PlanReport)
