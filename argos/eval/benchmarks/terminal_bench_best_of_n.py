from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Mapping

from argos.eval.benchmarks.terminal_bench import (
    TBTask,
    _build_docker_verify_cmd,
    _build_verify_cmd,
    classify,
    load_tb_task,
    to_eval_task,
)
from argos.i18n import t
from argos.workflow.engine import WorkflowEngine
from argos.workflow.result import AgentResult, StageResult
from argos.workflow.spec import (
    AgentTask,
    Stage,
    WorkflowSpec,
    parse_spec,
)

log = logging.getLogger(__name__)




def build_spec_for_task(
    tb_task: TBTask,
    *,
    n: int,
    model_tier: str,
    mirror_dir: Path | None = None,
) -> WorkflowSpec:
    if n < 1:
        raise ValueError(t("eval.bon.n_must_be_positive", n=n))
    cls = classify(tb_task)
    if cls.kind == "supported_in_docker":
        wd = mirror_dir if mirror_dir is not None else tb_task.source_dir
        verify_cmd = _build_docker_verify_cmd(tb_task, workdir=wd)
    else:
        import tempfile
        with tempfile.TemporaryDirectory() as _td:
            verify_cmd = _build_verify_cmd(tb_task, workdir=Path(_td))
    spec_dict = {
        "name": f"tb-bridge-{tb_task.task_id}",
        "description": (
            f"TB bridge: {tb_task.task_id} (N={n}, model={model_tier})"
        ),
        "stages": [{
            "id": tb_task.task_id,
            "op": "best_of_n",
            "n": n,
            "agent": {
                "prompt": tb_task.instruction,
                "tool_scope": "full",
                "isolation": "worktree",
                "verify": verify_cmd,
                "role": "coder",
                "model": model_tier,
            },
        }],
    }
    return parse_spec(spec_dict)




@dataclass(frozen=True, slots=True)
class BridgePerTask:
    n1_winner: str | None
    n3_winner: str | None
    n1_status: str            # passed | failed | error | setup_failed
    n3_status: str
    n1_candidates: tuple[AgentResult, ...]
    n3_candidates: tuple[AgentResult, ...]
    error: str | None = None


@dataclass(frozen=True, slots=True)
class BridgeReport:
    total_seen: int
    supported: int
    skipped: int
    n: int
    pass_at_1_n1: float
    pass_at_1_n3: float
    per_task: Mapping[str, BridgePerTask]
    per_task_status: Mapping[str, tuple[str, str]]
    unsupported_reasons: Mapping[str, int]




async def _drive_engine(engine: WorkflowEngine, spec: WorkflowSpec) -> StageResult:
    async for _ev in engine.run(spec):
        pass
    assert engine.last_result is not None
    return engine.last_result.stages[0]


def _status_of_winner(winner: AgentResult) -> str:
    if winner.verdict == "passed":
        return "passed"
    if winner.verdict == "unverifiable":
        return "unverifiable"
    return "failed"


def _passed_count(stage: StageResult) -> int:
    return sum(1 for r in stage.candidates if r.verdict == "passed")


def run_pass_at_1(
    task_dirs: Iterable[str | Path],
    *,
    engine: WorkflowEngine,
    n: int = 3,
    base_dir: Path,
    persist: bool = True,
    docker_available: bool | None = None,
) -> BridgeReport:
    if n < 1:
        raise ValueError(t("eval.bon.n_must_be_positive", n=n))
    base_dir = Path(base_dir)
    base_dir.mkdir(parents=True, exist_ok=True)

    supported = 0
    skipped = 0
    n1_passed = n3_passed = 0
    n1_total = n3_total = 0
    per_task: dict[str, BridgePerTask] = {}
    per_task_status: dict[str, tuple[str, str]] = {}
    reasons: dict[str, int] = {}

    for d in task_dirs:
        tb_task = load_tb_task(d)
        if tb_task is None:
            skipped += 1
            reasons["unparsable"] = reasons.get("unparsable", 0) + 1
            per_task_status[Path(d).name] = ("skipped", "task missing task.yaml/instruction")
            continue
        cls = classify(tb_task, docker_available=docker_available)
        if not cls.supported:
            skipped += 1
            reasons[cls.kind] = reasons.get(cls.kind, 0) + 1
            per_task_status[tb_task.task_id] = ("skipped", cls.reason)
            log.info("[bridge] skip %s — %s", tb_task.task_id, cls.reason)
            continue

        supported += 1
        cls = classify(tb_task, docker_available=docker_available)
        mirror = None
        prev_mirror = engine._factory.output_mirror
        try:
            object.__setattr__(engine._factory, "output_mirror", mirror)
        except Exception:
            pass

        try:
            spec_n1 = build_spec_for_task(tb_task, n=1, model_tier="default", mirror_dir=mirror)
            spec_nk = build_spec_for_task(tb_task, n=n, model_tier="default", mirror_dir=mirror)
            stage_n1 = asyncio.run(_drive_engine(engine, spec_n1))
            stage_nk = asyncio.run(_drive_engine(engine, spec_nk))
        except Exception as e:  # noqa: BLE001
            log.warning("[bridge] engine crashed on %s: %s", tb_task.task_id, e)
            per_task_status[tb_task.task_id] = ("error", f"{type(e).__name__}: {e}")
            per_task[tb_task.task_id] = BridgePerTask(
                n1_winner=None, n3_winner=None,
                n1_status="error", n3_status="error",
                n1_candidates=(), n3_candidates=(), error=str(e),
            )
            try:
                object.__setattr__(engine._factory, "output_mirror", prev_mirror)
            except Exception:
                pass
            continue
        try:
            object.__setattr__(engine._factory, "output_mirror", prev_mirror)
        except Exception:
            pass

        import logging as _lg
        for c in stage_n1.candidates:
            _lg.warning(
                "[bridge] N1 candidate %s: ok=%s verdict=%s err=%s",
                c.agent_id, c.ok, c.verdict,
                (c.error or "")[:200] if c.error else "",
            )
        for c in stage_nk.candidates:
            _lg.warning(
                "[bridge] Nk candidate %s: ok=%s verdict=%s err=%s",
                c.agent_id, c.ok, c.verdict,
                (c.error or "")[:200] if c.error else "",
            )

        w_n1 = stage_n1.results[0]
        s_n1 = _status_of_winner(w_n1)
        n1_total += 1
        if s_n1 == "passed":
            n1_passed += 1
        w_nk = stage_nk.results[0]
        s_nk = _status_of_winner(w_nk)
        n3_total += 1
        if s_nk == "passed":
            n3_passed += 1

        per_task[tb_task.task_id] = BridgePerTask(
            n1_winner=w_n1.agent_id,
            n3_winner=w_nk.agent_id,
            n1_status=s_n1,
            n3_status=s_nk,
            n1_candidates=stage_n1.candidates,
            n3_candidates=stage_nk.candidates,
        )
        final_status = s_nk if s_nk == "passed" else s_n1
        reason = "n3" if s_nk == "passed" else ("n1" if s_n1 == "passed" else "both_failed")
        per_task_status[tb_task.task_id] = (final_status, reason)

    pass_at_1_n1 = (n1_passed / n1_total) if n1_total else 0.0
    pass_at_1_n3 = (n3_passed / n3_total) if n3_total else 0.0
    return BridgeReport(
        total_seen=supported + skipped,
        supported=supported,
        skipped=skipped,
        n=n,
        pass_at_1_n1=pass_at_1_n1,
        pass_at_1_n3=pass_at_1_n3,
        per_task=per_task,
        per_task_status=per_task_status,
        unsupported_reasons=reasons,
    )
