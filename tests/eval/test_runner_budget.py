"""#7 EvalRunner --budget 强制执行测试。

覆盖:
  (a) budget_cost_usd 超限 → EvalResult.pass_status == "failed",error 含 "over_budget"
  (b) budget_s 超时 → EvalResult.pass_status == "failed",error 含 "timed_out"
  (c) 两个 budget 都为 None → 正常完成,无 over-budget 标记(纯加法,零副作用)

构造模式镜像 tests/eval/_fakes.py:FakeWorktree + make_fake_loop_factory。
"""
from __future__ import annotations

import time
from pathlib import Path

import pytest

from argos.eval.corpus import EvalTask
from argos.eval.runner import (
    PASS_FAILED,
    PASS_PASSED,
    EvalRunner,
    LoopOutcome,
)

from tests.eval._fakes import FakeWorktree, make_fake_loop, make_fake_loop_factory


def _make_task(tmp_path: Path) -> EvalTask:
    return EvalTask(
        id="t_budget",
        category="bug_fix",
        difficulty="easy",
        title="budget test task",
        goal="do something",
        verify_cmd="true",
        setup_cmd=None,
        expected_files=(),
        working_dir=tmp_path,
        corpus_version=1,
    )


def _make_runner(
    tmp_path: Path,
    loop,
    *,
    budget_s: int | None = None,
    budget_cost_usd: float | None = None,
) -> EvalRunner:
    wt = FakeWorktree(tmp_path / "wt")
    return EvalRunner(
        worktree=wt,
        base_dir=tmp_path / "eval",
        budget_s=budget_s,
        budget_cost_usd=budget_cost_usd,
        loop_factory=make_fake_loop_factory(loop),
    )


# ── (a) cost budget exceeded ──────────────────────────────────────────────────

def test_cost_budget_exceeded_marks_failed(tmp_path):
    """budget_cost_usd=0.0001; loop reports cost=0.013 → over-budget failure."""
    loop = make_fake_loop(cost_usd=0.013, verdict=PASS_PASSED)
    runner = _make_runner(tmp_path, loop, budget_cost_usd=0.0001)
    result = runner.run(_make_task(tmp_path), model_tier="fast")

    assert result.pass_status == PASS_FAILED
    assert "over_budget" in result.verify_detail


# ── (b) wall-clock budget exceeded ───────────────────────────────────────────

def test_time_budget_exceeded_marks_failed(tmp_path):
    """budget_s=1; loop sleeps 2s → timed-out failure."""

    class _SlowLoop:
        steps = 0
        tokens_in = 0
        tokens_out = 0
        cost_usd = 0.0

        def run_sync(self, goal: str, workspace: Path) -> LoopOutcome:
            time.sleep(2)
            return LoopOutcome(verdict_status=PASS_PASSED, cost_usd=0.0)

    runner = _make_runner(tmp_path, _SlowLoop(), budget_s=1)
    result = runner.run(_make_task(tmp_path), model_tier="fast")

    assert result.pass_status == PASS_FAILED
    assert "timed_out" in result.verify_detail


# ── (c) no budgets → normal completion ───────────────────────────────────────

def test_no_budget_completes_normally(tmp_path):
    """Both budgets None → run finishes normally, no over-budget flag."""
    loop = make_fake_loop(cost_usd=999.0, verdict=PASS_PASSED)  # huge cost, no limit
    runner = _make_runner(tmp_path, loop, budget_s=None, budget_cost_usd=None)
    result = runner.run(_make_task(tmp_path), model_tier="fast")

    assert result.pass_status == PASS_PASSED
    assert result.error is None
    assert "over_budget" not in (result.verify_detail or "")
