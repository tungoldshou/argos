from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from pathlib import Path

from argos.i18n import t
from argos.protocol.events import WorkflowProgress
from argos.workflow.result import AgentResult, StageResult, WorkflowResult
from argos.workflow.spec import AgentTask, Stage, WorkflowSpec
from argos.workflow.subagent import SubAgentFactory

_MAX_LOOP_ROUNDS = 5
_VOTE_YES = "[VOTE:YES]"


class WorkflowEngine:
    def __init__(self, factory: SubAgentFactory) -> None:
        self._factory = factory
        self.last_result: WorkflowResult | None = None
        self._q: asyncio.Queue = asyncio.Queue()

    async def run(self, spec: WorkflowSpec) -> AsyncIterator[WorkflowProgress]:
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
        if stage.op == "pipeline":
            return await self._run_pipeline(stage, prior, notes)
        if stage.op == "panel":
            return await self._run_panel(stage, prior, notes)
        if stage.op == "loop_until":
            return await self._run_loop_until(stage, prior, notes)
        if stage.op == "best_of_n":
            return await self._run_best_of_n(stage, prior, notes)
        return await self._run_fan_out(stage, prior, notes)

    async def _run_one(self, stage: Stage, task: AgentTask, idx_label, item) -> AgentResult:
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
                        return res
                    cur = res.output
                assert res is not None
                return res

        results = await asyncio.gather(*[_chain(i, it) for i, it in enumerate(items)])
        self._note_failures(stage, results, notes)
        return StageResult(stage_id=stage.id, results=tuple(results))

    async def _run_panel(self, stage: Stage, prior, notes) -> StageResult:
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
            t(
                "wf.engine.panel_note",
                stage_id=stage.id,
                yes=yes,
                voters=stage.voters,
                op=t("wf.engine.panel_gte") if passed else t("wf.engine.panel_lt"),
                threshold=stage.threshold,
                verdict=t("wf.engine.panel_passed") if passed else t("wf.engine.panel_failed"),
            )
        )
        self._note_failures(stage, results, notes)
        return StageResult(stage_id=stage.id, results=tuple(results))

    async def _run_loop_until(self, stage: Stage, prior, notes) -> StageResult:
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
                t(
                    "wf.engine.loop_until_capped",
                    stage_id=stage.id,
                    max_rounds=_MAX_LOOP_ROUNDS,
                    ok_total=ok_total,
                    target=stage.target,
                )
            )
        self._note_failures(stage, acc, notes)
        return StageResult(stage_id=stage.id, results=tuple(acc))

    @staticmethod
    def _is_yes(output: object) -> bool:
        return _VOTE_YES in str(output)

    async def _run_best_of_n(self, stage: Stage, prior, notes) -> StageResult:
        n = max(1, stage.n or 3)
        task = stage.agent[0] if isinstance(stage.agent, tuple) else stage.agent
        effective_cap = max(1, min(n, stage.cap))
        sem = asyncio.Semaphore(effective_cap)
        per_candidate_timeout_s = getattr(stage, "per_candidate_timeout_s", 1800.0)

        async def _candidate(idx: int) -> AgentResult:
            if stage.stagger_s > 0:
                await asyncio.sleep(idx * stage.stagger_s)
            async with sem:
                try:
                    return await asyncio.wait_for(
                        self._run_one(stage, task, f"c{idx}", None),
                        timeout=per_candidate_timeout_s,
                    )
                except asyncio.TimeoutError:
                    return AgentResult(
                        agent_id=f"{stage.id}#c{idx}",
                        ok=False,
                        output="",
                        verdict="unverifiable",
                        error=t(
                            "wf.engine.candidate_timeout",
                            idx=idx,
                            timeout=per_candidate_timeout_s,
                        ),
                        diff_file_count=0,
                    )

        results: tuple[AgentResult, ...] = tuple(
            await asyncio.gather(*[_candidate(i) for i in range(n)])
        )
        winner, stage_verdict, all_passed = self._pick_best_of_n_winner(results)
        passed_n = sum(1 for r in results if r.verdict == "passed")
        notes.append(
            t(
                "wf.engine.best_of_n_note",
                stage_id=stage.id,
                n=n,
                passed_n=passed_n,
                winner_id=winner.agent_id,
                winner_verdict="passed" if all_passed else stage_verdict,
            )
        )
        return StageResult(
            stage_id=stage.id,
            results=(winner,),
            candidates=results,
        )

    @staticmethod
    def _pick_best_of_n_winner(
        results: tuple[AgentResult, ...],
    ) -> tuple[AgentResult, str, bool]:
        if not results:
            return (
                AgentResult(agent_id="best_of_n#empty", ok=False, output="",
                            verdict="failed", error="no candidates"),
                "failed", False,
            )
        passed = [r for r in results if r.verdict == "passed"]
        if passed:
            indexed = list(enumerate(passed))
            indexed.sort(key=lambda ir: (ir[1].diff_file_count, ir[0]))
            return indexed[0][1], "passed", True
        ranked = sorted(
            enumerate(results),
            key=lambda ir: (
                0 if ir[1].ok else 1,
                0 if ir[1].verdict == "unverifiable" else 1,
                ir[1].diff_file_count,
                ir[0],
            ),
        )
        winner = ranked[0][1]
        any_unverifiable = any(r.verdict == "unverifiable" for r in results)
        stage_verdict = "unverifiable" if any_unverifiable else "failed"
        if winner.verdict != stage_verdict or winner.ok:
            winner = AgentResult(
                agent_id=winner.agent_id,
                ok=False,
                output=winner.output,
                verdict=stage_verdict,
                error=winner.error,
                tokens_in=winner.tokens_in,
                tokens_out=winner.tokens_out,
                diff_ref=winner.diff_ref,
                diff_summary=winner.diff_summary,
                diff_file_count=winner.diff_file_count,
            )
        return winner, stage_verdict, False

    @staticmethod
    def _note_failures(stage: Stage, results, notes) -> None:
        failed = [r for r in results if not r.ok]
        if failed:
            notes.append(
                t(
                    "wf.engine.failures_note",
                    stage_id=stage.id,
                    failed=len(failed),
                    total=len(results),
                )
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
            return t("wf.engine.synthesis_done") + " / ".join(notes)
        lines = []
        for sr in stage_results:
            ok = sum(1 for r in sr.results if r.ok)
            lines.append(f"[{sr.stage_id}] " + t("wf.engine.synthesis_stage_ok", ok=ok, total=len(sr.results)))
        return t("wf.engine.synthesis_done") + " · ".join(lines)

    @classmethod
    def for_test(cls, *, workspace: Path, model_factory) -> "WorkflowEngine":
        return cls(SubAgentFactory.for_test(workspace=workspace, model_factory=model_factory))
