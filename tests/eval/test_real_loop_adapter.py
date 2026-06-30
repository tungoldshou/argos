"""v1.1 real-loop adapter tests.

_drive() can now drive a real AgentLoop (async def run) and collect events
into a LoopOutcome without PASS_ERROR.

Tests cover:
- passed verdict collected correctly
- failed verdict collected correctly
- no VerifyVerdict → unverifiable (never fake-passed)
- CostUpdate + PhaseChange fields collected
- sync-bridge works from within an async test (no nested-loop crash)
- loop with neither run_sync nor async run → PASS_ERROR (honest error)
"""
from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest

from argos.eval.runner import (
    EvalRunner,
    PASS_PASSED,
    PASS_FAILED,
    PASS_UNVERIFIABLE,
    PASS_ERROR,
    LoopOutcome,
)
from argos.eval.corpus import EvalTask


# ── helpers ────────────────────────────────────────────────────────────────────

def _task(tmp_path: Path) -> EvalTask:
    return EvalTask(
        id="adapter-test",
        category="bug_fix",
        difficulty="easy",
        title="adapter test",
        goal="do something useful",
        verify_cmd="pytest -q",
        setup_cmd=None,
        expected_files=(),
        working_dir=tmp_path,
        corpus_version=1,
    )


def _make_runner(tmp_path: Path, budget_s=None, budget_cost_usd=None):
    class _FakeWorktree:
        pass

    return EvalRunner(
        worktree=_FakeWorktree(),
        base_dir=tmp_path / "eval",
        budget_s=budget_s,
        budget_cost_usd=budget_cost_usd,
    )


# ── fake async loops ───────────────────────────────────────────────────────────

def _make_loop(events):
    """Return an async-only loop that yields the given protocol event objects."""
    class _FakeLoop:
        async def run(self, goal: str, session_id: str = ""):
            for ev in events:
                yield ev

    return _FakeLoop()


def _verdict(status: str, detail: str = ""):
    """Build a minimal VerifyVerdict."""
    from argos.protocol.events import VerifyVerdict

    class _V:
        def __init__(self):
            self.status = status
            self.verify_detail = detail
            self.self_verified = False

    v = VerifyVerdict(verdict=_V())  # type: ignore[arg-type]
    return v


def _cost(tokens_in: int, tokens_out: int, cost_usd: float):
    from argos.protocol.events import CostUpdate
    return CostUpdate(tokens_in=tokens_in, tokens_out=tokens_out,
                      cost_usd=cost_usd, elapsed_s=0.1)


def _phase(actions: int, phase: str = "act"):
    from argos.protocol.events import PhaseChange
    return PhaseChange(phase=phase, actions=actions)  # type: ignore[arg-type]


# ── core adapter tests ─────────────────────────────────────────────────────────

def test_passed_verdict_collected(tmp_path: Path):
    """Loop yields VerifyVerdict(passed) → outcome.verdict_status == 'passed'."""
    runner = _make_runner(tmp_path)
    loop = _make_loop([_verdict("passed", "all tests green")])
    outcome = runner._drive(loop, _task(tmp_path), str(tmp_path))
    assert outcome.verdict_status == PASS_PASSED
    assert outcome.verify_detail == "all tests green"


def test_failed_verdict_collected(tmp_path: Path):
    """Loop yields VerifyVerdict(failed) → outcome.verdict_status == 'failed'."""
    runner = _make_runner(tmp_path)
    loop = _make_loop([_verdict("failed", "3 tests failed")])
    outcome = runner._drive(loop, _task(tmp_path), str(tmp_path))
    assert outcome.verdict_status == PASS_FAILED
    assert outcome.verify_detail == "3 tests failed"


def test_no_verdict_returns_unverifiable(tmp_path: Path):
    """Loop yields no VerifyVerdict → unverifiable (never fake-passed)."""
    runner = _make_runner(tmp_path)
    loop = _make_loop([])  # empty — no events at all
    outcome = runner._drive(loop, _task(tmp_path), str(tmp_path))
    assert outcome.verdict_status == PASS_UNVERIFIABLE, (
        "no VerifyVerdict emitted must map to unverifiable, not passed or error"
    )


def test_cost_and_phase_collected(tmp_path: Path):
    """CostUpdate + PhaseChange fields are correctly extracted."""
    runner = _make_runner(tmp_path)
    events = [
        _phase(5, "act"),
        _cost(100, 200, 0.003),
        _verdict("passed"),
    ]
    loop = _make_loop(events)
    outcome = runner._drive(loop, _task(tmp_path), str(tmp_path))
    assert outcome.verdict_status == PASS_PASSED
    assert outcome.tokens_in == 100
    assert outcome.tokens_out == 200
    assert abs((outcome.cost_usd or 0) - 0.003) < 1e-9
    assert outcome.steps == 5


def test_last_verdict_wins(tmp_path: Path):
    """When multiple VerifyVerdicts are emitted, the last one wins."""
    runner = _make_runner(tmp_path)
    loop = _make_loop([_verdict("failed"), _verdict("passed")])
    outcome = runner._drive(loop, _task(tmp_path), str(tmp_path))
    assert outcome.verdict_status == PASS_PASSED


def test_no_run_no_run_sync_returns_pass_error(tmp_path: Path):
    """Loop with neither run_sync nor async run → PASS_ERROR (honest error)."""
    class _EmptyLoop:
        pass

    runner = _make_runner(tmp_path)
    outcome = runner._drive(_EmptyLoop(), _task(tmp_path), str(tmp_path))
    assert outcome.verdict_status == PASS_ERROR


def test_run_sync_still_works(tmp_path: Path):
    """run_sync stub path is untouched (unit tests rely on it)."""
    class _SyncLoop:
        def run_sync(self, goal, workspace):
            return LoopOutcome(verdict_status=PASS_PASSED, verify_detail="sync path ok")

    runner = _make_runner(tmp_path)
    outcome = runner._drive(_SyncLoop(), _task(tmp_path), str(tmp_path))
    assert outcome.verdict_status == PASS_PASSED
    assert outcome.verify_detail == "sync path ok"


# ── sync-bridge: callable from inside async test (no nested-loop crash) ────────

@pytest.mark.asyncio
async def test_sync_bridge_no_nested_loop_crash(tmp_path: Path):
    """_drive() works when called from within an async context (pytest-asyncio).

    The ThreadPoolExecutor bridge runs asyncio.run() in a fresh thread,
    avoiding any nested-loop errors.
    """
    runner = _make_runner(tmp_path)
    loop = _make_loop([_verdict("passed", "from async test")])

    # Call the sync _drive from inside an async test — must not raise
    outcome = runner._drive(loop, _task(tmp_path), str(tmp_path))
    assert outcome.verdict_status == PASS_PASSED
    assert "async test" in outcome.verify_detail


# ── cost budget check on real-loop path ────────────────────────────────────────

def test_cost_over_budget_returns_failed(tmp_path: Path):
    """Real-loop path enforces cost budget (mirrors run_sync path)."""
    runner = _make_runner(tmp_path, budget_cost_usd=0.001)
    events = [_cost(100, 200, 5.0), _verdict("passed")]
    loop = _make_loop(events)
    outcome = runner._drive(loop, _task(tmp_path), str(tmp_path))
    assert outcome.verdict_status == PASS_FAILED
    assert "over_budget" in outcome.verify_detail


# ── caging: loop factory receives wt_path and cages the loop to it ─────────────

def test_loop_factory_receives_wt_path(tmp_path: Path):
    """EvalRunner passes wt_path to loop_factory; the loop must be caged to wt_path,
    NOT to the run's real _ws_path. This locks the isolation fix (caging bug).
    """
    wt_path = tmp_path / "eval-wt"
    wt_path.mkdir()
    other_ws = tmp_path / "real-repo"
    other_ws.mkdir()

    recorded_workspace: list[Path] = []

    class _FakeWorktree:
        def create(self, *, run_id, workspace):
            return str(wt_path)
        def cleanup(self, run_id):
            pass

    class _FakeLoop:
        _workspace = other_ws  # simulates loop baked to the real run's workspace

        async def run(self, goal: str, session_id: str = ""):
            from argos.protocol.events import VerifyVerdict
            from argos.core.types import Verdict
            recorded_workspace.append(self._workspace)
            vd = Verdict.passed("ok", None, 1)
            yield VerifyVerdict(verdict=vd)  # type: ignore[arg-type]

    def _factory(model_tier: str, wt: str) -> "_FakeLoop":
        loop = _FakeLoop()
        from pathlib import Path as _P
        loop._workspace = _P(wt).expanduser().resolve()
        return loop

    runner = EvalRunner(
        worktree=_FakeWorktree(),
        base_dir=tmp_path / "eval",
        loop_factory=_factory,
    )
    task = _task(tmp_path)
    result = runner.run(task, model_tier="cheap")

    assert len(recorded_workspace) == 1, "loop ran exactly once"
    assert recorded_workspace[0] == wt_path.resolve(), (
        f"loop was caged to {recorded_workspace[0]}, expected eval wt {wt_path.resolve()}"
    )
    assert recorded_workspace[0] != other_ws.resolve(), (
        "loop must NOT run in the real run workspace"
    )


# ── real Verdict field: `detail` not `verify_detail` ───────────────────────────

def _real_verdict(status: str, detail: str) -> "Any":
    """Build a VerifyVerdict backed by the real argos.core.types.Verdict."""
    from argos.protocol.events import VerifyVerdict
    from argos.core.types import Verdict
    if status == "passed":
        vd = Verdict.passed(detail, None, 1)
    else:
        vd = Verdict.failed(detail, None, 1)
    return VerifyVerdict(verdict=vd)  # type: ignore[arg-type]


def test_real_verdict_passed_detail_populated(tmp_path: Path):
    """VerifyVerdict backed by real Verdict(detail=...) populates verify_detail."""
    runner = _make_runner(tmp_path)
    loop = _make_loop([_real_verdict("passed", "all 42 tests green")])
    outcome = runner._drive(loop, _task(tmp_path), str(tmp_path))
    assert outcome.verdict_status == PASS_PASSED
    assert "42 tests green" in outcome.verify_detail, (
        f"detail not propagated; got verify_detail={outcome.verify_detail!r}"
    )


def test_real_verdict_failed_detail_populated(tmp_path: Path):
    """VerifyVerdict backed by real Verdict(failed, detail=...) propagates detail."""
    runner = _make_runner(tmp_path)
    loop = _make_loop([_real_verdict("failed", "2 assertions failed")])
    outcome = runner._drive(loop, _task(tmp_path), str(tmp_path))
    assert outcome.verdict_status == PASS_FAILED
    assert "assertions failed" in outcome.verify_detail, (
        f"detail not propagated; got verify_detail={outcome.verify_detail!r}"
    )
