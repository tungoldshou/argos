"""orchestrator 端到端测试 —— planner → fan-out → reducer → 报告;SSE 事件序列形状。"""
import asyncio
import pytest

from argos_agent import orchestrator, plan_schema, worker
from argos_agent.worker import WorkerResult


def _stub_planner(monkeypatch, n_tasks=3):
    """替 planner.planner_llm,直接返 N 摊的 PlanSpec(不走真 M3)。"""
    def fake_planner_llm(goal):
        from argos_agent.plan_schema import PlanSpec, PlanTask
        return PlanSpec(tasks=[PlanTask(goal=f"t{i} for {goal}", verify_cmd=f"echo {i}") for i in range(n_tasks)])
    monkeypatch.setattr(orchestrator, "planner_llm", fake_planner_llm)


def _stub_workers_pass(monkeypatch):
    async def fake_impl(task, ws, vd):
        return WorkerResult(task_id=task.task_id, verdict="passed", output_preview="ok")
    monkeypatch.setattr(worker, "_run_one_task_impl", fake_impl)


def test_orchestrator_runs_plan_to_completion(monkeypatch, tmp_path):
    from argos_agent import isolation
    monkeypatch.setattr(isolation, "RUNS_ROOT", tmp_path / "runs")
    _stub_planner(monkeypatch, n_tasks=3)
    _stub_workers_pass(monkeypatch)

    events = []
    async def collect():
        async for ev in orchestrator.run_plan(goal="test goal", session_id="sess-test"):
            events.append(ev)
    asyncio.run(collect())

    # 事件序列形状
    types = [e["type"] for e in events]
    assert types[0] == "plan:start"
    assert "plan:tasks" in types
    assert types.count("task:start") == 3
    assert types.count("task:verdict") == 3
    assert types[-1] == "plan:report"
    report = events[-1]
    assert report["split"] == 3 and report["succeeded"] == 3 and report["failed"] == 0
    assert report["replan_rounds"] == 0


def test_orchestrator_replan_loop_then_pass(monkeypatch, tmp_path):
    """模拟 1 摊失败 → reducer 出"补"动作 → planner 第二轮带反馈再拆 → 全过。"""
    from argos_agent import isolation, plan_schema
    monkeypatch.setattr(isolation, "RUNS_ROOT", tmp_path / "runs")

    call_count = {"n": 0}

    def fake_planner_llm(goal):
        call_count["n"] += 1
        from argos_agent.plan_schema import PlanSpec, PlanTask
        if call_count["n"] == 1:
            # 第一轮:3 摊
            return PlanSpec(tasks=[PlanTask(goal=f"t{i}", verify_cmd="x") for i in range(3)])
        # 第二轮(replan 触发):2 摊"补"
        return PlanSpec(tasks=[PlanTask(goal=f"fix-{i}", verify_cmd="x") for i in range(2)])

    monkeypatch.setattr(orchestrator, "planner_llm", fake_planner_llm)

    # 第一轮:task 0 fail;其余 pass;第二轮全 pass
    seen = {"n": 0}
    async def fake_impl(task, ws, vd):
        seen["n"] += 1
        # 第一轮 task 0 (= n=1) fail
        if seen["n"] == 1:
            return WorkerResult(task_id=task.task_id, verdict="failed", error="x", output_preview="")
        return WorkerResult(task_id=task.task_id, verdict="passed", output_preview="ok")
    monkeypatch.setattr(worker, "_run_one_task_impl", fake_impl)

    events = []
    async def collect():
        async for ev in orchestrator.run_plan(goal="x", session_id="sess-X"):
            events.append(ev)
    asyncio.run(collect())

    types = [e["type"] for e in events]
    # 至少有一次 task:verdict 失败 + 一次 task:verdict 成功(补) + 终态 report
    assert "task:verdict" in types
    report = events[-1]
    assert report["type"] == "plan:report"
    # 补轮数 ≥1(planner 被调了 2 次)
    assert call_count["n"] == 2
    assert report["replan_rounds"] >= 1


def test_orchestrator_planner_error_escalates(monkeypatch, tmp_path):
    """planner 抛 PlannerError → 出 plan:escalate 事件 + plan:report 终态。"""
    from argos_agent import isolation, plan_schema
    monkeypatch.setattr(isolation, "RUNS_ROOT", tmp_path / "runs")
    def fake_planner_llm(goal):
        raise plan_schema.PlannerError("M3 not available")
    monkeypatch.setattr(orchestrator, "planner_llm", fake_planner_llm)

    events = []
    async def collect():
        async for ev in orchestrator.run_plan(goal="x", session_id="sess-Y"):
            events.append(ev)
    asyncio.run(collect())

    types = [e["type"] for e in events]
    assert "plan:escalate" in types
    assert types[-1] == "plan:report"
    assert events[-1]["status"] == "escalated"
