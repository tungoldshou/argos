"""/plan 端点测试 —— POST /plan 返 SSE 流,事件名与 orchestrator 一致。"""
import pytest

from argos_agent import server, orchestrator, worker
from argos_agent.worker import WorkerResult


def _stub(monkeypatch, n_tasks=2, fail_first=False):
    def fake_planner_llm(goal):
        from argos_agent.plan_schema import PlanSpec, PlanTask
        return PlanSpec(tasks=[PlanTask(goal=f"t{i}", verify_cmd="x") for i in range(n_tasks)])
    monkeypatch.setattr(orchestrator, "planner_llm", fake_planner_llm)
    seen = {"n": 0}
    async def fake_impl(task, ws, vd):
        seen["n"] += 1
        if fail_first and seen["n"] == 1:
            return WorkerResult(task_id=task.task_id, verdict="failed", error="x", output_preview="")
        return WorkerResult(task_id=task.task_id, verdict="passed", output_preview="ok")
    monkeypatch.setattr(worker, "_run_one_task_impl", fake_impl)


def test_post_plan_returns_sse_event_stream(monkeypatch, tmp_path):
    from argos_agent import isolation
    monkeypatch.setattr(isolation, "RUNS_ROOT", tmp_path / "runs")
    _stub(monkeypatch, n_tasks=2)
    from fastapi.testclient import TestClient
    client = TestClient(server.app)
    r = client.post("/plan", json={"goal": "test", "session_id": "sess-test"})
    assert r.status_code == 200
    assert "text/event-stream" in r.headers["content-type"]
    body = r.text
    # 至少包含 plan:start / plan:tasks / task:start(×2) / task:verdict(×2) / plan:report
    for etype in ["plan:start", "plan:tasks", "task:start", "task:verdict", "plan:report"]:
        assert f"event: {etype}" in body, f"missing event {etype} in SSE body"


def test_post_plan_missing_goal_400():
    from fastapi.testclient import TestClient
    client = TestClient(server.app)
    r = client.post("/plan", json={})
    assert r.status_code == 422  # pydantic validation
