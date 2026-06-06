"""WorkflowEngine:解释 WorkflowSpec,异步并发跑五形态,出 WorkflowResult。
跑在主循环异步态(loop._run_workflow 里 async-for 消费其事件)。Esc 取消 → gather 取消 → 子工厂
RAII 拆资源。无声上限即诚实:cap 截断/部分失败经 notes + 进度事件如实报。

fan_out + synthesize 是通用并发执行;pipeline / panel / loop_until 在 _run_stage 的 op 分派点接入
(Task 8),语义确定可测。"""
from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from pathlib import Path

from argos_agent.tui.events import WorkflowProgress
from argos_agent.workflow.result import AgentResult, StageResult, WorkflowResult
from argos_agent.workflow.spec import AgentTask, Stage, WorkflowSpec
from argos_agent.workflow.subagent import SubAgentFactory

# loop_until 硬轮数上限:防失控(任何停止条件都失效时的兜底)。触顶往 notes 记诚实注记。
_MAX_LOOP_ROUNDS = 5
# panel voter 的赞成投票标记(v1 用确定标记匹配,不靠 NLP 猜)。
_VOTE_YES = "[VOTE:YES]"


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
        synthesis = self._synthesize(stage_results, notes)
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
        # op 分派:pipeline / panel / loop_until 各有确定语义;fan_out / synthesize 走通用并发。
        if stage.op == "pipeline":
            return await self._run_pipeline(stage, prior, notes)
        if stage.op == "panel":
            return await self._run_panel(stage, prior, notes)
        if stage.op == "loop_until":
            return await self._run_loop_until(stage, prior, notes)
        return await self._run_fan_out(stage, prior, notes)

    async def _run_one(self, stage: Stage, task: AgentTask, idx_label, item) -> AgentResult:
        """跑一个子 agent 并 emit act/done(error)阶段事件。idx_label 拼成 agent_id 后缀。"""
        agent_id = f"{stage.id}#{idx_label}"
        self._emit(stage.id, agent_id, "act")
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

    async def _run_fan_out(self, stage: Stage, prior, notes) -> StageResult:
        """通用并发:每 item 一个子 agent(同模板),Semaphore(cap) 限并发。"""
        items = self._items_for(stage, prior)
        sem = asyncio.Semaphore(stage.cap)
        task = stage.agent[0] if isinstance(stage.agent, tuple) else stage.agent

        async def _one(idx: int, item) -> AgentResult:
            async with sem:
                return await self._run_one(stage, task, idx, item)

        results = await asyncio.gather(*[_one(i, it) for i, it in enumerate(items)])
        self._note_failures(stage, results, notes)
        return StageResult(stage_id=stage.id, results=tuple(results))

    async def _run_pipeline(self, stage: Stage, prior, notes) -> StageResult:
        """每 item 独立串过多阶段模板(阶段间无 barrier);item 之间并发,item 内部串行。

        注意 cap 语义:此处 Semaphore(cap) 限的是**同时在飞的 item 数**(item 内多阶段
        串行,共用一张许可),区别于 fan_out 里 cap 限的是**同时在飞的 agent 调用数**。
        """
        items = self._items_for(stage, prior)
        templates = stage.agent if isinstance(stage.agent, tuple) else (stage.agent,)
        sem = asyncio.Semaphore(stage.cap)

        async def _chain(idx: int, item) -> AgentResult:
            async with sem:
                cur = item
                res: AgentResult | None = None
                for task in templates:
                    res = await self._run_one(stage, task, idx, cur)
                    if not res.ok:
                        return res          # 该 item 中途失败 → 提前结束,不拖累其它 item
                    cur = res.output         # 上阶段 output 作下阶段 item
                assert res is not None
                return res

        results = await asyncio.gather(*[_chain(i, it) for i, it in enumerate(items)])
        self._note_failures(stage, results, notes)
        return StageResult(stage_id=stage.id, results=tuple(results))

    async def _run_panel(self, stage: Stage, prior, notes) -> StageResult:
        """N 票表决:voters 个子 agent 同一输入,赞成票 >= threshold → 通过。决议写进 notes。"""
        items = self._items_for(stage, prior)
        item = items[0] if items else None
        task = stage.agent[0] if isinstance(stage.agent, tuple) else stage.agent
        sem = asyncio.Semaphore(stage.cap)

        async def _vote(k: int) -> AgentResult:
            async with sem:
                return await self._run_one(stage, task, f"vote{k}", item)

        results = await asyncio.gather(*[_vote(k) for k in range(stage.voters)])
        yes = sum(1 for r in results if r.ok and self._is_yes(r.output))
        passed = yes >= stage.threshold
        notes.append(
            f"panel「{stage.id}」{yes}/{stage.voters} 票 "
            f"{'≥' if passed else '<'} 阈值 {stage.threshold} → "
            f"{'通过' if passed else '未通过'}"
        )
        self._note_failures(stage, results, notes)
        return StageResult(stage_id=stage.id, results=tuple(results))

    async def _run_loop_until(self, stage: Stage, prior, notes) -> StageResult:
        """重复跑内层 fan_out,累计成功结果;到 target / 连续空轮 / 硬上限 任一即停。"""
        items = self._items_for(stage, prior)
        task = stage.agent[0] if isinstance(stage.agent, tuple) else stage.agent
        sem = asyncio.Semaphore(stage.cap)
        acc: list[AgentResult] = []
        ok_total = 0
        dry_streak = 0
        rounds = 0
        capped = False

        while True:
            rounds += 1

            async def _one(idx: int, item, rnd: int = rounds) -> AgentResult:
                async with sem:
                    return await self._run_one(stage, task, f"r{rnd}_{idx}", item)

            round_results = await asyncio.gather(
                *[_one(i, it) for i, it in enumerate(items)]
            )
            acc.extend(round_results)
            new_ok = sum(1 for r in round_results if r.ok)
            ok_total += new_ok
            dry_streak = 0 if new_ok > 0 else dry_streak + 1

            if stage.target is not None and ok_total >= stage.target:
                break
            if dry_streak >= stage.max_dry_rounds:
                break
            if rounds >= _MAX_LOOP_ROUNDS:
                capped = True
                break

        if capped:
            notes.append(
                f"loop_until「{stage.id}」触硬轮数上限 {_MAX_LOOP_ROUNDS} 轮停止"
                f"(累计成功 {ok_total} 个,未达 target {stage.target})"
            )
        self._note_failures(stage, acc, notes)
        return StageResult(stage_id=stage.id, results=tuple(acc))

    @staticmethod
    def _is_yes(output: object) -> bool:
        """panel 赞成票判定:output 含约定标记即记一票(确定,不靠 NLP)。"""
        return _VOTE_YES in str(output)

    @staticmethod
    def _note_failures(stage: Stage, results, notes) -> None:
        failed = [r for r in results if not r.ok]
        if failed:
            notes.append(
                f"stage「{stage.id}」{len(failed)}/{len(results)} 个 agent 失败(已带其余结果继续)"
            )

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
    def _synthesize(stage_results: list[StageResult], notes: list[str]) -> str:
        if stage_results and len(stage_results[-1].results) == 1:
            last = stage_results[-1].results[0]
            if last.ok and last.output:
                return str(last.output)
        if notes:
            return "工作流完成。" + " / ".join(notes)
        lines = []
        for sr in stage_results:
            ok = sum(1 for r in sr.results if r.ok)
            lines.append(f"[{sr.stage_id}] {ok}/{len(sr.results)} 成功")
        return "工作流完成。" + " · ".join(lines)

    @classmethod
    def for_test(cls, *, workspace: Path, model_factory) -> "WorkflowEngine":
        return cls(SubAgentFactory.for_test(workspace=workspace, model_factory=model_factory))
