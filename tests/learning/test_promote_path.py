"""Loop-4 power-on: passed run on daemon path reaches promote().

Tests assert that:
1. When runner_factory is provided and workspace exists with verify_cmd,
   promotion_gate.promote() is called (not just candidate-staging).
2. The auto-built EvalTask has correct workspace + verify_cmd.
3. When runner_factory=None, the old staging-only path is unchanged.
4. promote() exceptions fall back to candidate staging (fail-soft).
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from argos.learning import hook


def _write_run(tmp_path: Path, run_id: str, verify_cmd: str = "pytest -q") -> Path:
    runs_dir = tmp_path / "runs"
    runs_dir.mkdir(parents=True, exist_ok=True)
    p = runs_dir / f"{run_id}.jsonl"
    events = [
        {"kind": "session_start", "goal": "do something", "seq": 0},
        {"kind": "code_action", "code": "x = 1", "step": 0, "seq": 1},
        {"kind": "verify_verdict",
         "verdict": {"status": "passed", "verify_cmd": verify_cmd}, "seq": 2},
    ]
    with p.open("w") as fh:
        for ev in events:
            fh.write(json.dumps(ev) + "\n")
    return runs_dir


@pytest.mark.asyncio
async def test_passed_with_runner_factory_reaches_promote(tmp_path, monkeypatch):
    """Core Loop-4 test: runner_factory present → promote() is called, not just staged."""
    from argos.learning import distiller, promotion_gate
    from argos.learning.distiller import SkillCandidate

    # Fake workspace dir (must exist so EvalTask is built)
    ws = tmp_path / "workspace"
    ws.mkdir()

    promote_calls: list[dict] = []
    stage_calls: list = []

    monkeypatch.setattr(
        distiller, "distill_run_to_skill",
        lambda **kw: SkillCandidate(
            name="loop4-skill", body_markdown="# body\n",
            verify_cmd="pytest -q",
            skill_md_path=tmp_path / "skills" / "loop4-skill" / "SKILL.md",
        ),
    )

    def _fake_promote(*, candidate, tasks, runner, skills_root, **kw):
        promote_calls.append({
            "name": candidate.name,
            "tasks": tasks,
            "runner": runner,
        })
        from argos.learning.promotion_gate import PromotionResult
        return PromotionResult(promoted=False, reason="stubbed")

    monkeypatch.setattr(promotion_gate, "promote", _fake_promote)

    from argos.learning import candidates as cands_mod
    monkeypatch.setattr(
        cands_mod, "save_candidate",
        lambda *a, **kw: stage_calls.append(kw),
    )

    run_id = "abc123def456"
    runs_dir = _write_run(tmp_path, run_id)
    runner_sentinel = object()

    await hook.on_run_completed(
        run_id=run_id,
        store_dir=runs_dir,
        goal="do something",
        verify_cmd="pytest -q",
        verdict_status="passed",
        skills_root=tmp_path / "skills",
        candidates_root=tmp_path / "candidates",
        workspace=str(ws),
        runner_factory=lambda: runner_sentinel,
        tasks=[],  # empty → hook auto-builds from workspace+verify_cmd
    )

    # promote was reached
    assert len(promote_calls) == 1, "promote() must be called when runner_factory is live"
    assert promote_calls[0]["name"] == "loop4-skill"
    assert promote_calls[0]["runner"] is runner_sentinel

    # auto-built task has correct fields
    tasks = promote_calls[0]["tasks"]
    assert len(tasks) == 1
    assert tasks[0].verify_cmd == "pytest -q"
    assert tasks[0].working_dir == ws

    # candidate was NOT staged (promote branch was taken instead)
    assert stage_calls == [], "staging must NOT happen when promote branch is taken"


@pytest.mark.asyncio
async def test_auto_task_built_from_candidate_verify_cmd(tmp_path, monkeypatch):
    """EvalTask is built from candidate.verify_cmd (not the verify_cmd kwarg)."""
    from argos.learning import distiller, promotion_gate
    from argos.learning.distiller import SkillCandidate

    ws = tmp_path / "ws"
    ws.mkdir()

    task_spy: list = []

    monkeypatch.setattr(
        distiller, "distill_run_to_skill",
        lambda **kw: SkillCandidate(
            name="s", body_markdown="# b\n",
            verify_cmd="make test",   # candidate uses different cmd than kwarg
            skill_md_path=tmp_path / "skills" / "s" / "SKILL.md",
        ),
    )

    def _spy_promote(*, candidate, tasks, runner, skills_root, **kw):
        task_spy.extend(tasks)
        from argos.learning.promotion_gate import PromotionResult
        return PromotionResult(promoted=False, reason="ok")

    monkeypatch.setattr(promotion_gate, "promote", _spy_promote)

    run_id = "xyz789000000"
    runs_dir = _write_run(tmp_path, run_id, verify_cmd="pytest")

    await hook.on_run_completed(
        run_id=run_id, store_dir=runs_dir, goal="g",
        verify_cmd="pytest",  # this is from the run's verdict
        verdict_status="passed",
        skills_root=tmp_path / "skills",
        workspace=str(ws),
        runner_factory=lambda: object(),
        tasks=[],
    )

    assert len(task_spy) == 1
    assert task_spy[0].verify_cmd == "make test"  # from candidate, not kwarg


@pytest.mark.asyncio
async def test_no_runner_still_stages_candidate(tmp_path, monkeypatch):
    """runner_factory=None → unchanged staging-only path (regression guard)."""
    from argos.learning import distiller
    from argos.learning.distiller import SkillCandidate

    monkeypatch.setattr(
        distiller, "distill_run_to_skill",
        lambda **kw: SkillCandidate(
            name="staged", body_markdown="# b\n",
            verify_cmd="pytest",
            skill_md_path=tmp_path / "skills" / "staged" / "SKILL.md",
        ),
    )

    run_id = "abc123def456"
    runs_dir = _write_run(tmp_path, run_id)

    await hook.on_run_completed(
        run_id=run_id, store_dir=runs_dir, goal="g",
        verify_cmd="pytest", verdict_status="passed",
        skills_root=tmp_path / "skills",
        candidates_root=tmp_path / "candidates",
        workspace=str(tmp_path / "ws"),
        runner_factory=None,
        tasks=[],
    )

    from argos.learning.candidates import list_unconsumed
    staged = list_unconsumed(tmp_path / "candidates")
    assert len(staged) == 1


@pytest.mark.asyncio
async def test_promote_exception_falls_back_to_staging(tmp_path, monkeypatch):
    """promote() raises → fail-soft: candidate is staged, run is not crashed."""
    from argos.learning import distiller, promotion_gate
    from argos.learning.distiller import SkillCandidate

    ws = tmp_path / "ws"
    ws.mkdir()

    monkeypatch.setattr(
        distiller, "distill_run_to_skill",
        lambda **kw: SkillCandidate(
            name="boom", body_markdown="# b\n",
            verify_cmd="pytest",
            skill_md_path=tmp_path / "skills" / "boom" / "SKILL.md",
        ),
    )
    monkeypatch.setattr(
        promotion_gate, "promote",
        lambda **kw: (_ for _ in ()).throw(RuntimeError("eval crashed")),
    )

    run_id = "abc123def456"
    runs_dir = _write_run(tmp_path, run_id)

    # must not raise
    await hook.on_run_completed(
        run_id=run_id, store_dir=runs_dir, goal="g",
        verify_cmd="pytest", verdict_status="passed",
        skills_root=tmp_path / "skills",
        candidates_root=tmp_path / "candidates",
        workspace=str(ws),
        runner_factory=lambda: object(),
        tasks=[],
    )

    from argos.learning.candidates import list_unconsumed
    staged = list_unconsumed(tmp_path / "candidates")
    assert len(staged) == 1, "candidate must be staged when promote() crashes"
