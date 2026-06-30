"""Loop-4 inert-ceiling test — locks the known v1 behaviour.

EvalRunner._drive requires loop.run_sync (stub protocol).  A real AgentLoop
only has `async def run`; no run_sync.  Consequence: _drive returns PASS_ERROR
for both A and B → b_passed(0) <= a_passed(0) → promote() returns
no_improvement → no skill is ever auto-enabled in a live daemon.

This is PRE-EXISTING (not a batch-5 regression) and fails safe (never promotes,
never fakes a pass).  Test is here to document the ceiling so it cannot
silently change meaning.  When v1.1 wires a real-loop adapter the PASS_ERROR
assertion should be updated to verify the real adapter works.
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from argos.eval.runner import EvalRunner, PASS_ERROR
from argos.eval.corpus import EvalTask
from argos.learning.promotion_gate import PromotionResult


# ── minimal "real AgentLoop" stub — only has async def run, no run_sync ──────

class _AsyncOnlyLoop:
    """Mimics real AgentLoop: has async run() but no run_sync."""

    async def run(self, goal: str, session_id: str = ""):  # type: ignore[override]
        # would yield events in a real loop
        return  # type: ignore[misc]
        yield  # noqa: unreachable — makes this an async generator


# ── EvalTask helper ────────────────────────────────────────────────────────────

def _task(tmp_path: Path) -> EvalTask:
    return EvalTask(
        id="inert-test",
        category="bug_fix",
        difficulty="easy",
        title="inert test task",
        goal="do something",
        verify_cmd="pytest -q",
        setup_cmd=None,
        expected_files=(),
        working_dir=tmp_path,
        corpus_version=1,
    )


# ── fake WorktreeManager (only worktree_for is called in run()) ───────────────

class _FakeWorktree:
    def worktree_for(self, task_id: str, goal: str = ""):
        from contextlib import contextmanager

        @contextmanager
        def _cm():
            yield "/tmp/fake-wt"

        return _cm()


# ── core assertion: real-ish loop (no run_sync) → PASS_ERROR ─────────────────

def test_drive_returns_pass_error_for_real_loop(tmp_path: Path):
    """_drive with a loop lacking run_sync → PASS_ERROR (known v1 ceiling)."""
    from argos.eval.runner import EvalRunner, PASS_ERROR, LoopOutcome

    runner = EvalRunner(
        worktree=_FakeWorktree(),
        base_dir=tmp_path / "eval",
        loop_factory=lambda tier: _AsyncOnlyLoop(),
        budget_s=None,
        budget_cost_usd=None,
    )

    loop = _AsyncOnlyLoop()
    task = _task(tmp_path)
    outcome = runner._drive(loop, task, str(tmp_path))

    assert outcome.verdict_status == PASS_ERROR, (
        "v1 ceiling: real AgentLoop has no run_sync → _drive must return "
        "PASS_ERROR; update when v1.1 real-loop adapter is wired"
    )


# ── end-to-end: inert runner → promote() returns no_improvement ──────────────

def test_inert_runner_promote_returns_no_improvement(tmp_path: Path, monkeypatch):
    """Real-ish EvalRunner + no run_sync → promote() → no_improvement, no skill written."""
    from argos.learning.promotion_gate import promote
    from argos.learning.distiller import SkillCandidate

    skills_root = tmp_path / "skills"
    skills_root.mkdir()

    class _InertRunner:
        """run() delegates to EvalRunner._drive which returns PASS_ERROR."""

        def __init__(self):
            self._eval = EvalRunner(
                worktree=_FakeWorktree(),
                base_dir=tmp_path / "eval",
                loop_factory=lambda tier: _AsyncOnlyLoop(),
                budget_s=None,
                budget_cost_usd=None,
            )

        def run(self, task, *, model_tier: str = "default"):
            from argos.eval.runner import EvalResult, PASS_ERROR
            import time
            outcome = self._eval._drive(_AsyncOnlyLoop(), task, str(tmp_path))
            t = time.time()
            return EvalResult(
                task_id=task.id, run_id="inert-run", model_tier=model_tier,
                started_at=t, finished_at=t, duration_s=0.0,
                pass_status=outcome.verdict_status,
                verify_cmd=task.verify_cmd, verify_detail=outcome.verify_detail,
                tampered=(), tokens_in=0, tokens_out=0, cost_usd=0.0, steps=0,
                worktree_path=str(tmp_path), isolation_fallback=None,
                error=None, corpus_version=1, goal=task.goal,
            )

    cand = SkillCandidate(
        name="inert-skill",
        body_markdown="---\nname: inert-skill\nenabled: false\n---\n# body\n",
        verify_cmd="pytest -q",
        skill_md_path=skills_root / "inert-skill" / "SKILL.md",
    )
    runner = _InertRunner()
    result = promote(
        candidate=cand,
        tasks=[_task(tmp_path)],
        runner=runner,
        runner_b=runner,  # A==B both inert
        skills_root=skills_root,
    )

    assert result.promoted is False
    assert "no_improvement" in result.reason, (
        "v1 ceiling: both A and B get PASS_ERROR → no_improvement → "
        "no skill written; update when v1.1 real-loop adapter is wired"
    )
    # skill file must NOT have been written
    assert not (skills_root / "inert-skill" / "SKILL.md").exists()
