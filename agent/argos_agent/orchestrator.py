"""orchestrator —— 串联 planner → fan-out → reducer;SSE 事件桥。

每个 yield 出一个 dict(type, ...),server 端把这个 dict 序列化为 SSE 事件转发给前端。
事件名:plan:start / plan:tasks / task:start / task:verdict / plan:report / plan:escalate。

"补"回路:reducer 返 Replan → orchestrator 重新调 planner(带 failed_tasks 反馈)→ 再 fan-out。
最多 MAX_REPLAN_ROUNDS 轮(2),死循环成本上限 = 3x plan cost。
"""
from __future__ import annotations

import asyncio
from pathlib import Path
from typing import AsyncIterator, Dict, List

from . import fanout, isolation, plan_schema, planner, reducer
from .plan_schema import PlannerError, PlanTask, PlanSpec
from .planner import planner_llm  # 本地绑定,monkeypatch.setattr(orchestrator, "planner_llm", ...) 替换后此处解析到 monkeypatch 替身
from .worker import WorkerResult


async def run_plan(
    goal: str,
    session_id: str,
    project_dir: str | None = None,
) -> AsyncIterator[Dict]:
    """跑一个 plan,异步迭代 SSE 事件 dict。

    事件形状:
      {type: "plan:start", plan_id, goal, session_id}
      {type: "plan:tasks", tasks: [{id, goal, verify_cmd}, ...]}
      {type: "task:start", task_id, goal}
      {type: "task:verdict", task_id, verdict, output_preview, attempts, error}
      {type: "plan:report", split, succeeded, failed, replan_rounds, status, task_results}
      {type: "plan:escalate", reason}  # planner 失败 / 不降级
    """
    import uuid
    plan_id = uuid.uuid4().hex[:12]
    yield {"type": "plan:start", "plan_id": plan_id, "goal": goal, "session_id": session_id}

    replan_rounds = 0
    failed_feedback: List[WorkerResult] = []  # 累计失败 task,供下轮 planner 反馈
    # 按 task_id 去重的全量结果:成功者保留、补轮的新 task 累加(用于终态汇总)
    results_by_id: Dict[str, WorkerResult] = {}
    final_plan: List[PlanTask] = []
    escalated = False
    escalate_reason = ""

    while True:
        # 1) planner 拆活
        try:
            user_goal = goal
            if failed_feedback:
                user_goal = (
                    f"{goal}\n\n【补轮 {replan_rounds}】以下 task 上次失败:\n"
                    + "\n".join(
                        f"- task_id={r.task_id} verdict={r.verdict} error={r.error!r}"
                        for r in failed_feedback
                    )
                    + "\n请补 1-2 摊修复这些失败。"
                )
            spec = planner_llm(user_goal)
        except PlannerError as e:
            escalate_reason = str(e)
            escalated = True
            break

        # 2) 出 plan:tasks
        yield {"type": "plan:tasks", "plan_id": plan_id, "tasks": [
            {"id": t.task_id, "goal": t.goal, "verify_cmd": t.verify_cmd} for t in spec.tasks
        ]}
        final_plan.extend(spec.tasks)

        # 3) 给每个 task 算 (ws, vd);出 task:start ×K;再 fan-out
        plan_for_fanout: List = []
        for t in spec.tasks:
            try:
                if project_dir and isolation.is_git_project(project_dir):
                    ws, vd = isolation.acquire_worktree(
                        f"{session_id}-{t.task_id}", project_dir,
                    )
                else:
                    # sandbox:per-task 子目录
                    base = isolation.RUNS_ROOT / session_id / "tasks" / t.task_id
                    ws = (base / "workspace").resolve()
                    vd = (base / "verify").resolve()
                    ws.mkdir(parents=True, exist_ok=True)
                    vd.mkdir(parents=True, exist_ok=True)
            except isolation.IsolationError as e:
                # 隔离失败 → 标该 task failed,继续下一个
                yield {
                    "type": "task:verdict", "task_id": t.task_id, "verdict": "failed",
                    "error": f"isolation: {e!r}", "attempts": 0, "output_preview": "",
                }
                wr = WorkerResult(task_id=t.task_id, verdict="failed", error=f"isolation: {e!r}")
                results_by_id[t.task_id] = wr
                continue
            plan_for_fanout.append((t, ws, vd))
            yield {"type": "task:start", "task_id": t.task_id, "goal": t.goal}

        results = await fanout.fan_out(plan_for_fanout, session_id=session_id)
        for r in results:
            yield {
                "type": "task:verdict", "task_id": r.task_id, "verdict": r.verdict,
                "output_preview": r.output_preview, "attempts": r.attempts, "error": r.error,
            }
            # 同 task_id 累加(补轮 re-run 同一 task 时更新最新 verdict)
            results_by_id[r.task_id] = r

        # 4) reducer 决策
        decision = reducer.reduce(spec.tasks, results, replan_rounds=replan_rounds)
        if isinstance(decision, reducer.PlanReport):
            # 终态
            return_report = decision
            break
        # 补轮
        replan_rounds += 1
        failed_feedback = decision.failed_tasks

    # 5) 出终态 report
    all_results = list(results_by_id.values())  # 全量(含成功者+失败者+补轮的)
    if escalated:
        yield {"type": "plan:escalate", "reason": escalate_reason}
        yield {
            "type": "plan:report", "split": 0, "succeeded": 0, "failed": 0,
            "replan_rounds": replan_rounds, "status": "escalated",
            "task_results": [r.__dict__ for r in all_results],
        }
        return
    # 全量成功者 = all_results 中 verdict==passed 的;失败数 = 其余;split = 总 task 数
    succeeded = sum(1 for r in all_results if r.verdict == "passed")
    failed = len(all_results) - succeeded
    yield {
        "type": "plan:report",
        "split": len(all_results), "succeeded": succeeded, "failed": failed,
        "replan_rounds": return_report.replan_rounds,
        "status": "completed", "task_results": [r.__dict__ for r in all_results],
    }
