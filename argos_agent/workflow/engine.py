"""WorkflowEngine:解释 WorkflowSpec,异步并发跑五形态,出 WorkflowResult。
跑在主循环异步态(loop._run_workflow 里 async-for 消费其事件)。Esc 取消 → gather 取消 → 子工厂
RAII 拆资源。无声上限即诚实:cap 截断/部分失败经 notes + 进度事件如实报。

本 Task(7)只做 fan_out + synthesize 的通用并发执行;pipeline/panel/loop_until 留 Task 8 在
_run_stage 的 op 分派点接入。"""
from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from pathlib import Path

from argos_agent.tui.events import WorkflowProgress
from argos_agent.workflow.result import AgentResult, StageResult, WorkflowResult
from argos_agent.workflow.spec import Stage, WorkflowSpec
from argos_agent.workflow.subagent import SubAgentFactory


class WorkflowEngine:
    def __init__(self, factory: SubAgentFactory) -> None:
        self._factory = factory
        self.last_result: WorkflowResult | None = None
        self._q: asyncio.Queue = asyncio.Queue()

    async def run(self, spec: WorkflowSpec) -> AsyncIterator[WorkflowProgress]:
        """async-generator:yield 进度事件;结束后 self.last_result 可读。"""
        stage_results: list[StageResult] = []
        notes: list[str] = []
        prior: dict[str, StageResult] = {}
        ti = to = 0
        for stage in spec.stages:
            sr = await self._run_stage(spec, stage, prior, notes)
            stage_results.append(sr)
            prior[stage.id] = sr
            for r in sr.results:
                ti += r.tokens_in
                to += r.tokens_out
            for ev in self._drain():
                yield ev
        synthesis = self._synthesize(stage_results)
        self.last_result = WorkflowResult(
            name=spec.name, stages=tuple(stage_results), synthesis=synthesis,
            total_tokens_in=ti, total_tokens_out=to, notes=tuple(notes))

    def _emit(self, stage_id: str, agent_id: str, phase: str, note: str = "") -> None:
        self._q.put_nowait(
            WorkflowProgress(stage_id=stage_id, agent_id=agent_id, phase=phase, note=note)
        )

    def _drain(self) -> list:
        out = []
        while not self._q.empty():
            out.append(self._q.get_nowait())
        return out

    async def _run_stage(self, spec, stage: Stage, prior, notes) -> StageResult:
        # 本 Task:fan_out / synthesize 都走通用并发;其余 op(pipeline/panel/loop_until)Task 8 加分派。
        items = self._items_for(stage, prior)
        sem = asyncio.Semaphore(stage.cap)

        async def _one(idx: int, item) -> AgentResult:
            agent_id = f"{stage.id}#{idx}"
            async with sem:
                self._emit(stage.id, agent_id, "act")
                task = stage.agent if not isinstance(stage.agent, tuple) else stage.agent[0]
                res = await self._factory.run_task(
                    task, item=item, agent_id=agent_id,
                    on_phase=lambda a, p, n: self._emit(stage.id, a, p, n),
                )
                self._emit(
                    stage.id, agent_id,
                    "error" if not res.ok else "done",
                    res.error or (res.verdict or ""),
                )
                return res

        results = await asyncio.gather(*[_one(i, it) for i, it in enumerate(items)])
        failed = [r for r in results if not r.ok]
        if failed:
            notes.append(
                f"stage「{stage.id}」{len(failed)}/{len(results)} 个 agent 失败(已带其余结果继续)"
            )
        return StageResult(stage_id=stage.id, results=tuple(results))

    @staticmethod
    def _items_for(stage: Stage, prior) -> list:
        if stage.op == "synthesize":
            return [None]
        if isinstance(stage.over, dict) and "from" in stage.over:
            src = prior.get(stage.over["from"])
            return [r.output for r in src.results] if src else []
        if isinstance(stage.over, tuple):
            return list(stage.over)
        return [None]

    @staticmethod
    def _synthesize(stage_results: list[StageResult]) -> str:
        if stage_results and len(stage_results[-1].results) == 1:
            last = stage_results[-1].results[0]
            if last.ok and last.output:
                return str(last.output)
        lines = []
        for sr in stage_results:
            ok = sum(1 for r in sr.results if r.ok)
            lines.append(f"[{sr.stage_id}] {ok}/{len(sr.results)} 成功")
        return "工作流完成。" + " · ".join(lines)

    @classmethod
    def for_test(cls, *, workspace: Path, model_factory) -> "WorkflowEngine":
        return cls(SubAgentFactory.for_test(workspace=workspace, model_factory=model_factory))
