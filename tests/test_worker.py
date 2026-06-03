"""run_one_task 测试 —— 在 caller copy_context() 内设 per-task RunContext,
调 build_agent_with_gate + checkpointer,跑 astream,收 verdict,隔离区内不串台。"""
import asyncio
import pytest

from argos_agent import worker, plan_schema, runtime
from argos_agent.isolation import acquire_sandbox


def _stub_agent(monkeypatch, files_written: list):
    """替 worker._run_one_task_impl 为一个立刻写一个文件到当前 ctx.workspace 的 stub。

    复刻生产路径的 ctx 装配:set_context(project_mode=True) + set_current_gate(auto),
    否则 write_file 走模块默认 WORKSPACE(不是 caller 指定的 ws),sandbox 隔离验证就废了。
    """
    from argos_agent import tools, approval

    async def fake_run_one_task(task, ws, vd):
        from argos_agent import tools as t
        token = runtime.set_context(runtime.RunContext(
            workspace=ws, verify_dir=vd, project_mode=True,
        ))
        gtoken = approval.set_current_gate(worker._per_task_gate())
        try:
            await t.write_file.ainvoke({"path": f"{task.task_id}.txt", "content": task.goal})
            files_written.append((str(ws), task.task_id, task.goal))
            return worker.WorkerResult(task_id=task.task_id, verdict="passed", output_preview="ok")
        finally:
            approval.reset_current_gate(gtoken)
            runtime.reset(token)
    monkeypatch.setattr(worker, "_run_one_task_impl", fake_run_one_task)


@pytest.fixture
def sandbox_root(tmp_path, monkeypatch):
    from argos_agent import isolation
    monkeypatch.setattr(isolation, "RUNS_ROOT", tmp_path / "runs")
    return tmp_path


def test_run_one_task_writes_to_isolated_workspace(sandbox_root, monkeypatch):
    """worker 在自己的 (ws, vd) 写文件,写完产出含 task_id。"""
    files = []
    _stub_agent(monkeypatch, files)
    ws, vd = acquire_sandbox("sess-test")
    task = plan_schema.PlanTask(goal="do X", verify_cmd="echo x")
    res = asyncio.run(worker.run_one_task(task, ws, vd))
    assert res.verdict == "passed"
    assert len(files) == 1
    assert files[0][0] == str(ws)  # 写在 caller 指定的 ws
    assert files[0][1] == task.task_id  # 文件名是 task_id
    assert (ws / f"{task.task_id}.txt").read_text() == "do X"
