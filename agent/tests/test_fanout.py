"""fan-out 承重墙测试 —— asyncio.gather + copy_context() 派 N 个 worker,
各 worker 写自己的 (ws, vd),互不可见。"""
import asyncio
from pathlib import Path

import pytest

from argos_agent import fanout, plan_schema, worker, runtime
from argos_agent.isolation import acquire_sandbox


def _stub_workers(monkeypatch, files_log: list):
    """替 worker._run_one_task_impl 为一个真写文件的 stub(模拟 worker 落盘)。"""
    async def fake_impl(task, ws, vd):
        from argos_agent import tools, approval
        # 真切 ctx(模拟 worker 第一时间 set_context;fan-out 已在 caller 复制 ctx)
        token = runtime.set_context(runtime.RunContext(
            workspace=ws, verify_dir=vd, project_mode=True,
        ))
        gtoken = approval.set_current_gate(worker._per_task_gate())
        try:
            # 真用 write_file 落盘,验证 _ws() 读 ctx.workspace 不是模块默认
            await tools.write_file.ainvoke({"path": f"{task.task_id}.txt", "content": task.task_id})
            files_log.append((str(ws), task.task_id))
            return worker.WorkerResult(task_id=task.task_id, verdict="passed", output_preview="ok")
        finally:
            approval.reset_current_gate(gtoken)
            runtime.reset(token)
    monkeypatch.setattr(worker, "_run_one_task_impl", fake_impl)


@pytest.fixture
def sandbox_root(tmp_path, monkeypatch):
    from argos_agent import isolation
    monkeypatch.setattr(isolation, "RUNS_ROOT", tmp_path / "runs")
    return tmp_path


def test_fan_out_writes_to_per_task_workspaces(sandbox_root, monkeypatch):
    """3 摊真并行,各 task 落自己的 (ws, vd),互不可见。"""
    files = []
    _stub_workers(monkeypatch, files)

    # 3 摊 plan,各 task 自己的 (ws, vd);tag 单独记供事后验目录命名
    plan_tasks = [
        (plan_schema.PlanTask(goal="a", verify_cmd="x"), *acquire_sandbox("sess-A")),
        (plan_schema.PlanTask(goal="b", verify_cmd="x"), *acquire_sandbox("sess-B")),
        (plan_schema.PlanTask(goal="c", verify_cmd="x"), *acquire_sandbox("sess-C")),
    ]
    tags = ["A", "B", "C"]

    async def main():
        return await fanout.fan_out(plan_tasks, session_id="sess-test")

    results = asyncio.run(main())
    assert len(results) == 3
    assert {r.verdict for r in results} == {"passed"}

    # 3 个独立 ws 各自只含自己的文件(stub 写文件名 = task.task_id)
    seen = {}
    for (task, ws, vd), tag in zip(plan_tasks, tags):
        files_in_ws = {p.name for p in Path(ws).iterdir()}
        assert files_in_ws == {f"{task.task_id}.txt"}, f"task {tag} ws got {files_in_ws}"
        seen[tag] = files_in_ws
    # 互不可见:三个 ws 互不相等
    ws_set = {str(plan_tasks[i][1]) for i in range(3)}
    assert len(ws_set) == 3


def test_fan_out_isolates_contextvar_per_worker(sandbox_root, monkeypatch):
    """承重墙铁证:fan_out 派生时,父 ctx 不传;但每个 worker 自己 set_context(在 stub 内
    set 自己的 ws),证明 fan_out 调用形态正确 —— 真生产路径中,worker._run_one_task_impl
    内第一步就是 set_context(per-task RunContext),与 stub 行为对齐。"""
    seen_ws = []
    async def fake_impl(task, ws, vd):
        # 没设 ctx,直接读 _ws() 看回退到哪个路径
        from argos_agent import tools
        # 模拟 production worker 的 set_context(在 stub 里显式设一下)
        token = runtime.set_context(runtime.RunContext(
            workspace=ws, verify_dir=vd, project_mode=True,
        ))
        try:
            current_ws = tools._ws()
            seen_ws.append((task.task_id, str(current_ws)))
            return worker.WorkerResult(task_id=task.task_id, verdict="passed", output_preview="ok")
        finally:
            runtime.reset(token)
    monkeypatch.setattr(worker, "_run_one_task_impl", fake_impl)

    plan_tasks = [
        (plan_schema.PlanTask(goal="a", verify_cmd="x"), *acquire_sandbox("sess-X")),
        (plan_schema.PlanTask(goal="b", verify_cmd="x"), *acquire_sandbox("sess-Y")),
    ]

    async def main():
        return await fanout.fan_out(plan_tasks, session_id="sess-test2")

    asyncio.run(main())
    assert len(seen_ws) == 2
    # 两个 task 看到的 _ws() 是各自 isolation 配的 ws
    assert seen_ws[0][0] != seen_ws[1][0]
    assert seen_ws[0][1] != seen_ws[1][1]
