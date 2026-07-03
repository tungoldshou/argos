"""Internal documentation."""
from __future__ import annotations

import asyncio
import inspect
import logging
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

from argos.i18n import t
from argos.learning.candidates import StoredCandidate

if TYPE_CHECKING:
    from pathlib import Path

    from argos.learning.distiller import SkillCandidate

log = logging.getLogger(__name__)

DREAM_LOCK_NAME = ".dream.lock"

_NO_FCNTL_FD = -1


def _lock_path_for(candidates_root: "Path") -> "Path":
    """Internal documentation."""
    return candidates_root.parent / DREAM_LOCK_NAME


def _acquire_cross_process_lock(candidates_root: "Path") -> "int | None":
    """Internal documentation."""
    try:
        import fcntl
    except ImportError:  # pragma: no cover
        log.warning("dream: 平台无 fcntl,降级为仅进程内锁(跨进程并发不防护)")
        return _NO_FCNTL_FD

    import os

    lock_path = _lock_path_for(candidates_root)
    try:
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(str(lock_path), os.O_CREAT | os.O_WRONLY, 0o600)
    except OSError as e:
        log.warning("dream: 锁文件打开失败,降级仅进程内锁: %s", e)
        return _NO_FCNTL_FD
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        os.close(fd)
        return None
    return fd


def _release_cross_process_lock(fd: "int | None") -> None:
    """Internal documentation."""
    if fd is None or fd == _NO_FCNTL_FD:
        return
    import os
    try:
        os.close(fd)
    except OSError as e:  # noqa: BLE001
        log.warning("dream: 锁释放失败(已忽略): %s", e)


SIM_THRESHOLD = 0.35
DEFAULT_MAX_UNITS = 3
MAX_UNIT_SOURCES = 5

_FENCE_RE = re.compile(r"```.*?```", re.DOTALL)
_TILDE_FENCE_RE = re.compile(r"~~~.*?~~~", re.DOTALL)
_CODE_BLOCK_RE = re.compile(r"```python\n(.*?)```", re.DOTALL)
_TOKEN_RE = re.compile(r"[a-z0-9一-鿿]+")


@dataclass(frozen=True, slots=True)
class DreamUnit:
    """Internal documentation."""
    sources: tuple[StoredCandidate, ...]


def _tokens(text: str) -> set[str]:
    return set(_TOKEN_RE.findall((text or "").lower()))


def _token_sim(a: str, b: str) -> float:
    """Internal documentation."""
    ta, tb = _tokens(a), _tokens(b)
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


def _sig(c: StoredCandidate) -> str:
    return f"{c.goal} {c.verify_cmd or ''}"


def _cost_rank_key(c: StoredCandidate) -> tuple:
    """Sort key: passed verdict first, then lower cost_usd, then fewer steps.

    Used to rank candidates within a DreamUnit so synthesize() picks the
    best-performing source as sources[0] (verify_cmd anchor, narrative focus).
    ponytail: sort key only, no new framework.
    """
    verdict_order = 0 if c.verdict_status == "passed" else 1
    cost = c.cost_usd if c.cost_usd is not None else float("inf")
    return (verdict_order, cost, c.steps)


def cluster_candidates(
    cands: list[StoredCandidate], *, max_units: int = DEFAULT_MAX_UNITS,
) -> list[DreamUnit]:
    """Internal documentation."""
    clusters: list[list[StoredCandidate]] = []
    for c in cands:
        for cl in clusters:
            if _token_sim(_sig(c), _sig(cl[0])) >= SIM_THRESHOLD:
                cl.append(c)
                break
        else:
            clusters.append([c])
    multi = [cl[:MAX_UNIT_SOURCES] for cl in clusters if len(cl) >= 2]
    single = [cl for cl in clusters if len(cl) == 1]
    picked = multi[:max_units] + single[:max_units]
    return [DreamUnit(sources=tuple(cl)) for cl in picked]


def _strip_code_blocks(text: str) -> str:
    """Internal documentation."""
    out = _FENCE_RE.sub("", text or "")
    out = _TILDE_FENCE_RE.sub("", out)
    cuts = [p for p in (out.find("```"), out.find("~~~")) if p != -1]
    if cuts:
        out = out[:min(cuts)]
    return out.strip()


def _extract_code(body_markdown: str) -> str:
    """Internal documentation."""
    return "\n\n".join(m.strip() for m in _CODE_BLOCK_RE.findall(body_markdown or ""))


def _merged_name(unit: DreamUnit) -> str:
    from argos.learning.distiller import slugify_goal
    return ("dream-" + slugify_goal(unit.sources[0].goal))[:40]


def narrative_prompt(unit: DreamUnit) -> str:
    """Internal documentation."""
    return (
        t("learn.dream.narrative_prompt")
        + "\n".join(f"- {s.goal}" for s in unit.sources)
    )


def synthesize(
    unit: DreamUnit, *, narrative: str | None = None,
) -> "SkillCandidate | None":
    """Internal documentation."""
    from pathlib import Path

    from argos.learning.distiller import SkillCandidate

    if not unit.sources:
        return None
    name = _merged_name(unit)
    runs = [s.source_run for s in unit.sources]

    text = _strip_code_blocks(narrative or "")
    if not text:
        text = t("learn.dream.synthesize_fallback", n=len(unit.sources))

    lines = [
        "---",
        f"name: {name}",
        "capabilities: []",
        "enabled: false",
        f"source_runs: [{', '.join(runs)}]",
        "---",
        "",
        f"# {name}",
        "",
        "## When to use",
        "",
        text,
        "",
        "## Verified sources",
        "",
    ]
    for s in unit.sources:
        lines += [f"### source_run {s.source_run}", "", f"**Goal**: {s.goal}", ""]
        code = _extract_code(s.body_markdown)
        if code:
            lines += ["```python", code, "```", ""]
        if s.verify_cmd:
            lines += ["Verify:", "", "```bash", s.verify_cmd, "```", ""]
    return SkillCandidate(
        name=name,
        body_markdown="\n".join(lines),
        verify_cmd=unit.sources[0].verify_cmd,
        skill_md_path=Path("unpromoted"),
    )


@dataclass(frozen=True, slots=True)
class HintedRunner:
    """Internal documentation."""
    inner: object
    hint: str
    max_hint_len: int = 4000

    def run(self, task, *, model_tier: str):
        import dataclasses
        truncated = (self.hint or "")[:self.max_hint_len]
        hinted = dataclasses.replace(
            task, goal=f"{t('learn.dream.hinted_runner_prefix')}{truncated}\n\n---\n\n{task.goal}")
        return self.inner.run(hinted, model_tier=model_tier)


def build_eval_tasks(unit: DreamUnit) -> tuple[list, list]:
    """Internal documentation."""
    from pathlib import Path as _Path

    from argos.eval.corpus import EvalTask

    tasks: list = []
    gone: list[StoredCandidate] = []
    for s in unit.sources:
        ws = _Path(s.workspace) if s.workspace else None
        if ws is None or not ws.exists():
            gone.append(s)
            continue
        if not s.verify_cmd:
            gone.append(s)
            continue
        tasks.append(EvalTask(
            id=f"dream-{s.source_run[:12]}", category="dream", difficulty="n/a",
            title=s.goal[:60], goal=s.goal, verify_cmd=s.verify_cmd,
            setup_cmd=None, expected_files=(), working_dir=ws, corpus_version=0,
        ))
    return tasks, gone



@dataclass(frozen=True, slots=True)
class DreamReport:
    """Internal documentation."""
    units_total: int = 0
    promoted: int = 0
    rejected: int = 0
    skipped: int = 0
    memory_merged: int = 0
    memory_archived: int = 0
    report_path: str = ""


def has_material(candidates_root: "Path", *, min_units: int = 1) -> bool:
    """Internal documentation."""
    from argos.learning.candidates import list_unconsumed
    return len(list_unconsumed(candidates_root)) >= min_units


class DreamPipeline:
    """Internal documentation."""

    def __init__(
        self, *,
        candidates_root: "Path",
        skills_root: "Path",
        memory_dir: "Path",
        dreams_dir: "Path",
        runner_factory,                       # (hint: str | None) -> runner
        narrate=None,                         # (prompt: str) -> str | Awaitable[str]
        broadcast_fn=None,                    # (payload: dict) -> None
        max_units: int = DEFAULT_MAX_UNITS,
    ) -> None:
        self._candidates_root = candidates_root
        self._skills_root = skills_root
        self._memory_dir = memory_dir
        self._dreams_dir = dreams_dir
        self._runner_factory = runner_factory
        self._narrate = narrate
        self._broadcast_fn = broadcast_fn
        self._max_units = max_units
        self._lock: "asyncio.Lock | None" = None

    @property
    def is_running(self) -> bool:
        """Internal documentation."""
        return self._lock is not None and self._lock.locked()

    def cross_process_busy(self) -> bool:
        """Internal documentation."""
        fd = _acquire_cross_process_lock(self._candidates_root)
        if fd is None:
            return True
        _release_cross_process_lock(fd)
        return False

    async def run(self) -> "DreamReport | None":
        """Internal documentation."""
        import asyncio
        if self._lock is None:
            self._lock = asyncio.Lock()
        if self._lock.locked():
            log.info("dream: 已有整合在跑,跳过本次(进程内单飞)")
            return None
        async with self._lock:
            lock_fd = _acquire_cross_process_lock(self._candidates_root)
            if lock_fd is None:
                log.info("dream: 另一进程的整合在跑,跳过本次(跨进程单飞)")
                return None
            try:
                return await self._run_locked()
            finally:
                _release_cross_process_lock(lock_fd)

    async def _run_locked(self) -> "DreamReport":
        import time

        from argos.learning.candidates import list_unconsumed

        promoted = rejected = skipped = 0

        self._emit("dream_progress", stage="scan", detail="", ts=time.time())
        cands = list_unconsumed(self._candidates_root)
        # Rank by cost-efficiency before clustering so sources[0] in each DreamUnit
        # is the cheapest verified candidate (synthesize/build_eval_tasks use sources[0]).
        cands = sorted(cands, key=_cost_rank_key)
        units = cluster_candidates(cands, max_units=self._max_units)
        self._emit("dream_progress", stage="cluster",
                   detail=f"{len(units)} units", ts=time.time())

        for unit in units:
            try:
                outcome = await self._process_unit(unit)
                promoted += outcome[0]
                rejected += outcome[1]
                skipped += outcome[2]
            except Exception as e:  # noqa: BLE001
                log.warning("dream: 单元处理失败,跳过: %s", e)
                skipped += 1

        self._emit("dream_progress", stage="memory", detail="", ts=time.time())
        try:
            from argos.memory.consolidate import consolidate
            mem_report = consolidate(self._memory_dir)
        except Exception as e:  # noqa: BLE001
            from argos.memory.consolidate import ConsolidationReport
            log.warning("dream: 记忆整理失败,降级空报告: %s", e)
            mem_report = ConsolidationReport()

        report = DreamReport(
            units_total=len(units),
            promoted=promoted, rejected=rejected, skipped=skipped,
            memory_merged=mem_report.merged, memory_archived=mem_report.archived,
        )
        ts = time.time()
        report_path = self._write_report_line(report, ts=ts)
        report = DreamReport(
            units_total=report.units_total, promoted=report.promoted,
            rejected=report.rejected, skipped=report.skipped,
            memory_merged=report.memory_merged, memory_archived=report.memory_archived,
            report_path=report_path,
        )
        self._emit("dream_progress", stage="done", detail="", ts=ts)
        self._emit(
            "dream_report",
            units_total=report.units_total, promoted=report.promoted,
            rejected=report.rejected, skipped=report.skipped,
            memory_merged=report.memory_merged, memory_archived=report.memory_archived,
            report_path=report.report_path, ts=ts,
        )
        return report

    async def _process_unit(self, unit: "DreamUnit") -> tuple[int, int, int]:
        """Internal documentation."""
        import inspect

        from argos.learning.candidates import mark_consumed
        from argos.learning.promotion_gate import promote

        narrative: "str | None" = None
        if self._narrate is not None:
            try:
                raw = self._narrate(narrative_prompt(unit))
                narrative = (await raw) if inspect.isawaitable(raw) else raw
            except Exception as e:  # noqa: BLE001
                log.warning("dream: 叙述生成失败,模板兜底: %s", e)
                narrative = None

        cand = synthesize(unit, narrative=narrative)
        if cand is None:
            return (0, 0, 1)

        tasks, gone = build_eval_tasks(unit)
        for s in gone:
            mark_consumed(s.path, reason="workspace_gone")
        if not tasks:
            return (0, 0, 1)

        import asyncio
        res = await asyncio.to_thread(
            promote,
            candidate=cand, tasks=tasks,
            runner=self._runner_factory(None),
            runner_b=self._runner_factory(cand.body_markdown),
            skills_root=self._skills_root,
        )

        live = [s for s in unit.sources if s not in gone]
        if res.promoted:
            for s in live:
                mark_consumed(s.path, reason="promoted")
            result = (1, 0, 0)
        elif res.reason.startswith("no_improvement"):
            for s in live:
                mark_consumed(s.path, reason="rejected_ab")
            result = (0, 1, 0)
        elif res.reason.startswith("name_collision:"):
            for s in live:
                mark_consumed(s.path, reason="name_collision")
            result = (0, 0, 1)
        else:
            result = (0, 0, 1)

        import time
        self._emit("dream_progress", stage="promote",
                   detail=res.reason, ts=time.time())
        return result

    def _write_report_line(self, report: "DreamReport", *, ts: float) -> str:
        """Internal documentation."""
        from datetime import datetime

        from argos.jsonl_log import append_line
        try:
            day = datetime.fromtimestamp(ts).strftime("%Y-%m-%d")
            path = self._dreams_dir / f"{day}.jsonl"
            append_line(path, {
                "ts": ts,
                "units_total": report.units_total,
                "promoted": report.promoted,
                "rejected": report.rejected,
                "skipped": report.skipped,
                "memory_merged": report.memory_merged,
                "memory_archived": report.memory_archived,
            })
            return str(path)
        except Exception as e:  # noqa: BLE001
            log.warning("dream: 报告落盘失败: %s", e)
            return ""

    def _emit(self, kind: str, **payload) -> None:
        """Internal documentation."""
        if self._broadcast_fn is None:
            return
        try:
            result = self._broadcast_fn({"kind": kind, **payload})
            if inspect.iscoroutine(result):
                try:
                    loop = asyncio.get_running_loop()
                    loop.create_task(result)
                except RuntimeError:
                    asyncio.run(result)
        except Exception as e:  # noqa: BLE001
            log.warning("dream: 事件广播失败(%s): %s", kind, e)
