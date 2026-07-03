"""Internal documentation."""
from __future__ import annotations

import json
import logging
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterable

log = logging.getLogger(__name__)


def _read_events(store_dir: Path, run_id: str) -> list[dict]:
    p = Path(store_dir) / f"{run_id}.jsonl"
    if not p.exists():
        return []
    try:
        text = p.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return []
    out: list[dict] = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict):
            out.append(obj)
    return out


@dataclass
class _MiniStore:
    runs_dir: Path

    def replay(self, run_id: str) -> Iterable[dict]:
        return iter(_read_events(self.runs_dir, run_id))


async def on_run_completed(
    *,
    run_id: str,
    store_dir: Path,
    goal: str,
    verify_cmd: str | None,
    verdict_status: str,
    self_verified: bool = False,
    skills_root: Path,
    candidates_root: Path | None = None,
    workspace: str | None = None,
    runner_factory: Callable[[], Any] | None = None,
    tasks: list | None = None,
) -> None:
    """Internal documentation."""
    is_user_pass = (verdict_status == "passed") and not self_verified
    if is_user_pass:
        await _on_passed(
            run_id=run_id, store_dir=store_dir,
            goal=goal, verify_cmd=verify_cmd,
            skills_root=skills_root,
            candidates_root=candidates_root,
            workspace=workspace,
            runner_factory=runner_factory, tasks=tasks or [],
        )
    else:
        await _on_failed(
            run_id=run_id, store_dir=store_dir,
            goal=goal, verify_cmd=verify_cmd,
            verdict_status=verdict_status,
            self_verified=self_verified,
            skills_root=skills_root,
        )


async def _on_passed(
    *,
    run_id: str, store_dir: Path, goal: str, verify_cmd: str | None,
    skills_root: Path,
    candidates_root: Path | None,
    workspace: str | None,
    runner_factory: Callable[[], Any] | None,
    tasks: list,
) -> None:
    """Internal documentation."""
    try:
        from argos.learning import distiller, promotion_gate

        mini_store = _MiniStore(runs_dir=Path(store_dir))
        cand = distiller.distill_run_to_skill(
            run_id=run_id, store=mini_store,
            goal=goal, verify_cmd=verify_cmd,
            skills_root=skills_root,
        )
    except Exception as e:  # noqa: BLE001
        log.warning("learning: distill failed for %s: %s", run_id, e)
        return

    if cand is None:
        return

    # Loop-4: if runner_factory is present but tasks is empty, auto-build an
    # EvalTask from the candidate's workspace + verify_cmd so the promote branch
    # is reachable without callers having to pre-construct tasks.
    effective_tasks: list = list(tasks) if tasks else []
    if runner_factory is not None and not effective_tasks and workspace and cand.verify_cmd:
        try:
            from argos.eval.corpus import EvalTask
            ws_path = Path(workspace)
            if ws_path.exists():
                effective_tasks = [EvalTask(
                    id=f"learn-{run_id[:12]}",
                    category="learning",
                    difficulty="n/a",
                    title=(goal or "")[:60],
                    goal=goal or "",
                    verify_cmd=cand.verify_cmd,
                    setup_cmd=None,
                    expected_files=(),
                    working_dir=ws_path,
                    corpus_version=0,
                )]
        except Exception as e:  # noqa: BLE001
            log.warning("learning: EvalTask build failed for %s: %s", run_id, e)

    if not effective_tasks or runner_factory is None:
        if candidates_root is not None:
            try:
                from argos.learning import candidates as _cands
                _cands.save_candidate(
                    cand, root=candidates_root, source_run=run_id,
                    workspace=workspace, goal=goal,
                )
            except Exception as e:  # noqa: BLE001
                log.warning("learning: 候选落盘失败 %s: %s", run_id, e)
        return

    try:
        runner = runner_factory()
        # Build a hinted B-runner so B runs with the candidate skill prepended
        # to the task goal (same as Dream's HintedRunner path).  A=bare / B=hinted
        # means a win is genuine improvement, not flakiness on A==B.
        # ponytail: reuse dream.HintedRunner; no new class needed.
        try:
            from argos.learning.dream import HintedRunner
            runner_b = HintedRunner(inner=runner, hint=cand.body_markdown)
        except Exception as _hr_err:  # noqa: BLE001
            log.warning(
                "learning: HintedRunner unavailable for %s (%s); "
                "skipping promote (degenerate A==B avoided) → staging candidate",
                run_id, _hr_err,
            )
            if candidates_root is not None:
                try:
                    from argos.learning import candidates as _cands
                    _cands.save_candidate(
                        cand, root=candidates_root, source_run=run_id,
                        workspace=workspace, goal=goal,
                    )
                except Exception as _ce:  # noqa: BLE001
                    log.warning("learning: 候选落盘失败 %s: %s", run_id, _ce)
            return
        promotion_gate.promote(
            candidate=cand, tasks=effective_tasks, runner=runner,
            runner_b=runner_b,
            skills_root=skills_root,
        )
    except Exception as e:  # noqa: BLE001
        # Fail-soft: promotion eval failed → stage candidate for Dream instead
        log.warning("learning: promote failed for %s, staging candidate: %s", run_id, e)
        if candidates_root is not None:
            try:
                from argos.learning import candidates as _cands
                _cands.save_candidate(
                    cand, root=candidates_root, source_run=run_id,
                    workspace=workspace, goal=goal,
                )
            except Exception as _ce:  # noqa: BLE001
                log.warning("learning: 候选落盘失败 %s: %s", run_id, _ce)


async def _on_failed(
    *,
    run_id: str, store_dir: Path, goal: str, verify_cmd: str | None,
    verdict_status: str,
    self_verified: bool = False,
    skills_root: Path,
) -> None:
    """Internal documentation."""
    try:
        from argos.learning.reflection import reflect_failure
        reflect_failure(
            run_id=run_id, store_dir=Path(store_dir),
            goal=goal, verify_cmd=verify_cmd,
            verdict_status=verdict_status,
            self_verified=self_verified,
            skills_root=skills_root,
        )
    except Exception as e:  # noqa: BLE001
        log.warning("learning: reflect_failure failed for %s: %s", run_id, e)
