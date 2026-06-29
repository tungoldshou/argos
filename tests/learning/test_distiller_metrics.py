"""distiller metrics + Dream cost-efficiency ranking tests (Task 3.3).

Covers:
1. replay containing verify_verdict / cost_update / phase_change → SkillCandidate metric fields
2. Dream ranking: two candidates for same skill are ordered cheaper-first (passed-first)
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from argos.learning.distiller import distill_run_to_skill, SkillCandidate
from argos.learning.candidates import StoredCandidate
from argos.learning.dream import _cost_rank_key, cluster_candidates


# ── helpers ──────────────────────────────────────────────────────────────────

def _write_events(tmp_path: Path, run_id: str, events: list[dict]) -> object:
    """Write events to a RunStore-compatible JSONL path; return a minimal store."""
    runs_dir = tmp_path / "runs"
    runs_dir.mkdir(parents=True, exist_ok=True)
    p = runs_dir / f"{run_id}.jsonl"
    with p.open("w", encoding="utf-8") as fh:
        for ev in events:
            fh.write(json.dumps(ev, ensure_ascii=False) + "\n")

    class _FakeStore:
        def __init__(self, d):
            self.runs_dir = d
        def replay(self, rid):
            f = self.runs_dir / f"{rid}.jsonl"
            return [json.loads(l) for l in f.read_text().splitlines() if l.strip()]

    return _FakeStore(runs_dir)


def _full_events(
    *,
    goal: str = "test goal",
    verify_cmd: str = "pytest -q",
    code: str = "x = 1",
    verdict_status: str = "passed",
    tokens_in: int = 100,
    tokens_out: int = 50,
    cost_usd: float | None = 0.01,
    actions_at_verify: int = 5,
) -> list[dict]:
    """Build a replay with code_action + verify_verdict + cost_update + phase_change."""
    evs = [
        {"kind": "session_start", "goal": goal, "seq": 0},
        {"kind": "phase_change", "phase": "plan", "actions": 0, "seq": 1},
        {"kind": "code_action", "code": code, "step": 2, "seq": 2},
        {"kind": "cost_update", "tokens_in": tokens_in, "tokens_out": tokens_out,
         "cost_usd": cost_usd, "elapsed_s": 1.0, "seq": 3},
        {"kind": "phase_change", "phase": "verify", "actions": actions_at_verify, "seq": 4},
        {
            "kind": "verify_verdict",
            "verdict": {"status": verdict_status, "reason": "ok", "verify_cmd": verify_cmd},
            "seq": 5,
        },
    ]
    return evs


# ── Test 1: distiller captures all metric events ──────────────────────────────

def test_distiller_captures_verify_verdict(tmp_path):
    """verify_verdict event → SkillCandidate.verdict_status set."""
    store = _write_events(tmp_path, "r1", _full_events(verdict_status="passed"))
    cand = distill_run_to_skill(
        run_id="r1", store=store,
        goal="test goal", verify_cmd="pytest -q",
        skills_root=tmp_path / "skills",
    )
    assert cand is not None
    assert cand.verdict_status == "passed"


def test_distiller_captures_cost_update(tmp_path):
    """cost_update event → tokens_in / tokens_out / cost_usd on candidate."""
    store = _write_events(tmp_path, "r2", _full_events(tokens_in=200, tokens_out=80, cost_usd=0.02))
    cand = distill_run_to_skill(
        run_id="r2", store=store,
        goal="test goal", verify_cmd="pytest -q",
        skills_root=tmp_path / "skills",
    )
    assert cand is not None
    assert cand.tokens_in == 200
    assert cand.tokens_out == 80
    assert cand.cost_usd == pytest.approx(0.02)


def test_distiller_captures_phase_change_steps(tmp_path):
    """phase_change actions → SkillCandidate.steps."""
    store = _write_events(tmp_path, "r3", _full_events(actions_at_verify=7))
    cand = distill_run_to_skill(
        run_id="r3", store=store,
        goal="test goal", verify_cmd="pytest -q",
        skills_root=tmp_path / "skills",
    )
    assert cand is not None
    assert cand.steps == 7


def test_distiller_cost_usd_none_when_unknown(tmp_path):
    """cost_update with cost_usd=None → candidate.cost_usd stays None."""
    store = _write_events(tmp_path, "r4", _full_events(cost_usd=None))
    cand = distill_run_to_skill(
        run_id="r4", store=store,
        goal="test goal", verify_cmd="pytest -q",
        skills_root=tmp_path / "skills",
    )
    assert cand is not None
    assert cand.cost_usd is None


def test_distiller_defaults_when_no_metric_events(tmp_path):
    """Replay with only code_action (no metric events) → safe defaults."""
    events = [
        {"kind": "session_start", "goal": "g", "seq": 0},
        {"kind": "code_action", "code": "x = 1", "step": 1, "seq": 1},
    ]
    store = _write_events(tmp_path, "r5", events)
    cand = distill_run_to_skill(
        run_id="r5", store=store,
        goal="g", verify_cmd=None,
        skills_root=tmp_path / "skills",
    )
    assert cand is not None
    assert cand.verdict_status is None
    assert cand.tokens_in == 0
    assert cand.tokens_out == 0
    assert cand.cost_usd is None
    assert cand.steps == 0


# ── Test 2: Dream ranking ─────────────────────────────────────────────────────

def _sc(
    name: str, goal: str,
    verdict_status: str | None = "passed",
    cost_usd: float | None = None,
    steps: int = 0,
    run: str = "run0000000000ab",
) -> StoredCandidate:
    return StoredCandidate(
        name=name, body_markdown="# s\n```python\nx=1\n```",
        verify_cmd="pytest -q",
        source_run=run, workspace="/tmp/p", goal=goal,
        path=Path("/dev/null"),
        verdict_status=verdict_status,
        cost_usd=cost_usd, steps=steps,
    )


def test_cost_rank_key_passed_before_failed():
    """passed verdict sorts before failed/unverifiable."""
    passed = _sc("a", "g", verdict_status="passed", cost_usd=1.0)
    failed = _sc("b", "g", verdict_status="failed", cost_usd=0.01)
    assert _cost_rank_key(passed) < _cost_rank_key(failed)


def test_cost_rank_key_cheaper_first_when_same_verdict():
    """Among same verdict, lower cost_usd comes first."""
    cheap = _sc("a", "g", verdict_status="passed", cost_usd=0.01)
    expensive = _sc("b", "g", verdict_status="passed", cost_usd=0.99)
    assert _cost_rank_key(cheap) < _cost_rank_key(expensive)


def test_cost_rank_key_fewer_steps_tiebreak():
    """Same verdict + same cost → fewer steps wins."""
    lean = _sc("a", "g", verdict_status="passed", cost_usd=0.05, steps=3)
    verbose = _sc("b", "g", verdict_status="passed", cost_usd=0.05, steps=10)
    assert _cost_rank_key(lean) < _cost_rank_key(verbose)


def test_cost_rank_key_none_cost_last():
    """cost_usd=None (unknown) sorts after any known cost."""
    known = _sc("a", "g", verdict_status="passed", cost_usd=999.0)
    unknown = _sc("b", "g", verdict_status="passed", cost_usd=None)
    assert _cost_rank_key(known) < _cost_rank_key(unknown)


def test_dream_ranking_two_candidates_cheaper_first():
    """cluster_candidates on pre-sorted cands keeps cheaper candidate first in unit.sources."""
    expensive = _sc("a", "fix login bug", verdict_status="passed",
                    cost_usd=0.50, run="run0000000000aa")
    cheap = _sc("b", "fix login bug auth", verdict_status="passed",
                cost_usd=0.05, run="run0000000000bb")

    # Simulate what _run_locked does: sort then cluster
    cands = sorted([expensive, cheap], key=_cost_rank_key)
    units = cluster_candidates(cands)

    assert len(units) == 1
    assert units[0].sources[0].source_run == "run0000000000bb"  # cheap is first
