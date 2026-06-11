"""WorkflowEngine:解释 WorkflowSpec,异步并发跑五形态,出 WorkflowResult。
跑在主循环异步态(loop._run_workflow 里 async-for 消费其事件)。Esc 取消 → gather 取消 → 子工厂
RAII 拆资源。无声上限即诚实:cap 截断/部分失败经 notes + 进度事件如实报。

fan_out + synthesize 是通用并发执行;pipeline / panel / loop_until 在 _run_stage 的 op 分派点接入
(Task 8),语义确定可测。"""
from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from pathlib import Path

from argos_agent.protocol.events import WorkflowProgress
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
        if stage.op == "best_of_n":
            return await self._run_best_of_n(stage, prior, notes)
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

    async def _run_best_of_n(self, stage: Stage, prior, notes) -> StageResult:
        """best_of_n:同任务并行 N 个候选,各自 worktree + 各自跑,选第一个 passed 的。

        选择规则(诚实,deterministic):
          · 任一候选 verdict == 'passed' → winner = 第一个 passed
            (完成顺序由 gather 收齐时由底层调度,异步顺序不保证;tie-break:
             改文件数 diff_file_count 升序,再 ties 时取下标小者 — 仍 deterministic)
          · 全部未 passed → winner = "最不坏"的一个:
              ok=True (跑成功了,只是 verify 没让过) 优先于 ok=False
              然后 verdict='unverifiable' 优先于 'failed'(诚实区分:测不了 ≠ 没过)
              再按 diff_file_count 升序
            但 stage.results 里的 winner 仍标 ok=False,verdict = 'failed' 或
            'unverifiable'(取所有候选里"最差"的;都 failed 取 failed;都 unverifiable
            取 unverifiable;mixed → unverifiable 优先被如实标,因含"不可判"成分)
            防止"无 passed 时假装成功":若全 unverifiable → stage.verdict=unverifiable;
            否则 stage.verdict=failed。
        复用:
          · SubAgentFactory.run_task → 各自独立 worktree + 各自真 verify(不 mock)
          · diff 摘要模式(SubAgentFactory.inline_diff 默认 False)→ 不撑爆父上下文
          · 进度事件经 EventBus 走 _emit;每个候选 act/done
        拒绝"用 mock 把沙箱测试假跑过":候选数 N 必须真跑真 verify(本方法不替 caller
        决定 N 是不是 0/1 — spec 解析已夹到 ≥ 1,夹后仍真跑)。
        """
        n = max(1, stage.n or 3)
        task = stage.agent[0] if isinstance(stage.agent, tuple) else stage.agent
        # 限并发 + 错峰:M3 / agnes-flash 等严 QPS 模型,N 候选同帧打 API 会全 429(2026-06-09
        # 实测:N=3 cap=4 默认时 3 候选全 429)。effective_cap = min(n, stage.cap) 让 cap 真正生效
        # 而不是被 n 撑爆;stagger 让候选 i 在 idx * stagger_s 之后才争 sem,不平摊同帧。
        effective_cap = max(1, min(n, stage.cap))
        sem = asyncio.Semaphore(effective_cap)
        # per-candidate timeout:防单个候选 hang 死(模型 stream 不返)拖垮整 bench(2026-06-09
        # 真用户场景:M3 限流时 stream 偶尔无响应,asyncio.gather 等永远,bench 跑不完)。
        # 超时 → 候选标 verdict='unverifiable' + error 含 'timeout',其它候选照常。
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
                    # 候选未在 timeout 内返:不让它拖死整 stage。标 unverifiable
                    # (winner 选择时与 'failed' 同档处理,不会冒充 passed)。
                    return AgentResult(
                        agent_id=f"{stage.id}#c{idx}",
                        ok=False,
                        output="",
                        verdict="unverifiable",
                        error=(
                            f"per_candidate_timeout: 候选 c{idx} 超过 "
                            f"{per_candidate_timeout_s}s 未完成,被取消"
                        ),
                        diff_file_count=0,
                    )

        # gather 让 N 真并发;asyncio 不保证完成顺序,下面 _pick_winner 用确定 tie-break
        results: tuple[AgentResult, ...] = tuple(
            await asyncio.gather(*[_candidate(i) for i in range(n)])
        )
        winner, stage_verdict, all_passed = self._pick_best_of_n_winner(results)
        # notes:如实记录 best_of_n 跑了几个、几个 passed、winner 选了哪个
        passed_n = sum(1 for r in results if r.verdict == "passed")
        notes.append(
            f"best_of_n「{stage.id}」N={n} 跑了 {n} 个候选,"
            f"passed={passed_n} → winner={winner.agent_id}"
            f"({'passed' if all_passed else stage_verdict})"
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
        """从 N 个候选里挑 winner + 派生 stage verdict。返 (winner, stage_verdict, all_passed)。

        stage_verdict 取值:
          · 'passed'    至少 1 个 passed → 已 OK,winner 即 passed 那个
          · 'failed'    全 failed
          · 'unverifiable' 全 unverifiable
          · 'failed'    mixed(unverifiable + failed) → 用 failed(更"坏"的如实标)
        winner 在全非 passed 时的偏好:
          ok=True 优先(跑通了的,只是 verify 没让过)> ok=False
          verdict='unverifiable' 优于 'failed'(因 unverifiable 含义是"测不了",诚实
            不等于"答案错";人看到 unverifiable 知道可能是测试本身有毛病而非模型差)
          再按 diff_file_count 升序(改动小优先)
          再按下标升序(完全 tie 时确定,即便不期望发生)
        """
        if not results:
            # 防御性:N 解析时已夹 ≥ 1,但保险
            return (
                AgentResult(agent_id="best_of_n#empty", ok=False, output="",
                            verdict="failed", error="no candidates"),
                "failed", False,
            )
        passed = [r for r in results if r.verdict == "passed"]
        if passed:
            # tie-break:diff 越小越好;同 diff 时按下标(用 enumerate 原始位置)
            indexed = list(enumerate(passed))
            indexed.sort(key=lambda ir: (ir[1].diff_file_count, ir[0]))
            return indexed[0][1], "passed", True
        # 全非 passed:挑最不坏
        ranked = sorted(
            enumerate(results),
            key=lambda ir: (
                0 if ir[1].ok else 1,                          # ok=True 优先
                0 if ir[1].verdict == "unverifiable" else 1,   # unverifiable 优于 failed
                ir[1].diff_file_count,                          # 改动小优先
                ir[0],                                          # 同分按下标
            ),
        )
        winner = ranked[0][1]
        # 派 stage verdict:有任一 unverifiable → unverifiable(因"测不了"更诚实);
        # 否则全 failed
        any_unverifiable = any(r.verdict == "unverifiable" for r in results)
        stage_verdict = "unverifiable" if any_unverifiable else "failed"
        # 强制把 winner 校到 stage_verdict(便于调用方只看 winner 也知道汇总态);
        # 无 passed 时 **必然** ok=False —— 哪怕原候选 ok=True("跑通但 verify 没过"也不能
        # 假装 passed)。这是 best_of_n 诚实铁律。
        if winner.verdict != stage_verdict or winner.ok:
            winner = AgentResult(
                agent_id=winner.agent_id,
                ok=False,                    # 关键:无 passed 时 winner 一定 ok=False
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
