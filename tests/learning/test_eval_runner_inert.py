"""Loop-4 real-loop adapter tests — updated for v1.1.

v1.0 ceiling (now resolved): EvalRunner._drive returned PASS_ERROR for loops
with only `async def run` and no run_sync.

v1.1 adapter: _drive now drives a real async run() loop and collects events
into LoopOutcome. A loop with NEITHER run_sync NOR async run still errors
honestly (PASS_ERROR). promote() with real loops can now produce real verdicts.
"""
from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from argos.eval.runner import (
    EvalRunner, PASS_ERROR, PASS_UNVERIFIABLE, PASS_PASSED, PASS_FAILED,
    LoopOutcome,
)
from argos.eval.corpus import EvalTask
from argos.learning.promotion_gate import PromotionResult


# ── helpers ────────────────────────────────────────────────────────────────────

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


class _FakeWorktree:
    def worktree_for(self, task_id: str, goal: str = ""):
        from contextlib import contextmanager

        @contextmanager
        def _cm():
            yield "/tmp/fake-wt"

        return _cm()


def _make_runner(tmp_path: Path, loop_factory):
    return EvalRunner(
        worktree=_FakeWorktree(),
        base_dir=tmp_path / "eval",
        loop_factory=loop_factory,
        budget_s=None,
        budget_cost_usd=None,
    )


# ── async-only loop stubs ──────────────────────────────────────────────────────

class _AsyncOnlyLoopEmpty:
    """async run() that yields nothing → unverifiable (no VerifyVerdict emitted)."""

    async def run(self, goal: str, session_id: str = ""):
        return
        yield  # makes it an async generator


class _AsyncOnlyLoopNoAttr:
    """Has neither run_sync nor run — the true no-op case."""
    pass


# ── v1.1 tests: async run() is now driven, not errored ────────────────────────

def test_drive_async_only_loop_no_verdict_returns_unverifiable(tmp_path: Path):
    """v1.1: loop with async run() but no VerifyVerdict → unverifiable (never fake-passed)."""
    runner = _make_runner(tmp_path, lambda tier: _AsyncOnlyLoopEmpty())
    loop = _AsyncOnlyLoopEmpty()
    task = _task(tmp_path)
    outcome = runner._drive(loop, task, str(tmp_path))

    assert outcome.verdict_status == PASS_UNVERIFIABLE, (
        "v1.1: no VerifyVerdict emitted → must return unverifiable, never PASS_ERROR or fake passed"
    )


def test_drive_no_run_no_run_sync_returns_pass_error(tmp_path: Path):
    """A loop with NEITHER run_sync NOR async run → PASS_ERROR (honest error)."""
    runner = _make_runner(tmp_path, lambda tier: _AsyncOnlyLoopNoAttr())
    loop = _AsyncOnlyLoopNoAttr()
    task = _task(tmp_path)
    outcome = runner._drive(loop, task, str(tmp_path))

    assert outcome.verdict_status == PASS_ERROR, (
        "loop with no run_sync and no async run must return PASS_ERROR honestly"
    )


# ── end-to-end: inert runner with async loop → promote() returns no_improvement ──

def test_inert_runner_promote_returns_no_improvement(tmp_path: Path, monkeypatch):
    """EvalRunner with async-only loop (no VerifyVerdict) → unverifiable → no_improvement.

    v1.1: the loop IS driven (adapter fires), but unverifiable → still no promotion.
    This confirms the honesty invariant: no VerifyVerdict → never auto-promoted.
    """
    from argos.learning.promotion_gate import promote
    from argos.learning.distiller import SkillCandidate

    skills_root = tmp_path / "skills"
    skills_root.mkdir()

    class _InertRunner:
        """run() delegates to EvalRunner._drive which returns unverifiable (no verdict)."""

        def __init__(self):
            self._eval = EvalRunner(
                worktree=_FakeWorktree(),
                base_dir=tmp_path / "eval",
                loop_factory=lambda tier: _AsyncOnlyLoopEmpty(),
                budget_s=None,
                budget_cost_usd=None,
            )

        def run(self, task, *, model_tier: str = "default"):
            from argos.eval.runner import EvalResult, PASS_UNVERIFIABLE
            import time
            outcome = self._eval._drive(_AsyncOnlyLoopEmpty(), task, str(tmp_path))
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
        runner_b=runner,  # A==B both unverifiable
        skills_root=skills_root,
    )

    assert result.promoted is False
    assert "no_improvement" in result.reason, (
        "v1.1: both A and B return unverifiable → no_improvement → no skill written"
    )
    # skill file must NOT have been written
    assert not (skills_root / "inert-skill" / "SKILL.md").exists()
