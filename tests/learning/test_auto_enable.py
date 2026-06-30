"""test_auto_enable: 通过 A/B gate 的技能写盘后 enabled:true;未通过的不写/不启用。

Task 5a.2 验收测试。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import pytest

from argos.learning import promotion_gate


# ── helpers ──────────────────────────────────────────────────────────────────

def _make_task(task_id: str = "t1", verify_cmd: str = "true"):
    from argos.eval.corpus import EvalTask
    return EvalTask(
        id=task_id, category="self_check", difficulty="easy",
        title=f"task {task_id}", goal=f"goal {task_id}", verify_cmd=verify_cmd,
        setup_cmd=None, expected_files=(), working_dir=Path("/tmp"),
        corpus_version=1,
    )


def _make_candidate(name: str, *, body: str | None = None):
    from argos.learning.distiller import SkillCandidate
    # Simulate the template body produced by dream.synthesize() — enabled:false until gate flips it
    body = body or (
        "---\n"
        f"name: {name}\n"
        "capabilities: []\n"
        "enabled: false\n"
        f"source_runs: [run-abc]\n"
        "---\n\n"
        f"# {name}\n\nDo the thing.\n"
    )
    return SkillCandidate(
        name=name, body_markdown=body, verify_cmd="pytest -q",
        skill_md_path=Path(f"/tmp/skills/{name}/SKILL.md"),
    )


class _FailRunner:
    def run(self, task, *, model_tier: str):
        from argos.eval.runner import EvalResult
        return EvalResult(
            task_id=task.id, run_id="r-fail", model_tier=model_tier,
            started_at=0.0, finished_at=0.0, duration_s=0.0,
            pass_status="failed", verify_cmd=task.verify_cmd,
            verify_detail="nope", tampered=(),
            tokens_in=10, tokens_out=5, cost_usd=0.001, steps=1,
            worktree_path="", isolation_fallback=None, error=None,
            corpus_version=task.corpus_version, goal=task.goal,
        )


class _PassRunner:
    def run(self, task, *, model_tier: str):
        from argos.eval.runner import EvalResult
        return EvalResult(
            task_id=task.id, run_id="r-pass", model_tier=model_tier,
            started_at=0.0, finished_at=0.0, duration_s=0.0,
            pass_status="passed", verify_cmd=task.verify_cmd,
            verify_detail="ok", tampered=(),
            tokens_in=10, tokens_out=5, cost_usd=0.001, steps=1,
            worktree_path="", isolation_fallback=None, error=None,
            corpus_version=task.corpus_version, goal=task.goal,
        )


# ── tests ────────────────────────────────────────────────────────────────────

def test_passing_ab_gate_writes_enabled_true(tmp_path):
    """A candidate that PASSES the A/B gate is written enabled:true."""
    tasks = [_make_task("t1"), _make_task("t2")]
    cand = _make_candidate("auto-skill")

    result = promotion_gate.promote(
        candidate=cand,
        tasks=tasks,
        runner=_FailRunner(),   # A side: all fail
        runner_b=_PassRunner(), # B side: all pass  → b_passed > a_passed
        skills_root=tmp_path / "skills",
    )

    assert result.promoted is True
    skill_md = (tmp_path / "skills" / "auto-skill" / "SKILL.md").read_text(encoding="utf-8")
    assert "enabled: true" in skill_md
    assert "enabled: false" not in skill_md


def test_failing_ab_gate_does_not_write_skill(tmp_path):
    """A candidate that does NOT pass the A/B gate (tie/regression) is NOT written."""
    tasks = [_make_task("t1")]
    cand = _make_candidate("no-improve-skill")

    result = promotion_gate.promote(
        candidate=cand,
        tasks=tasks,
        runner=_PassRunner(),   # A side: pass
        runner_b=_PassRunner(), # B side: also pass → tie → no improvement
        skills_root=tmp_path / "skills",
    )

    assert result.promoted is False
    assert not (tmp_path / "skills" / "no-improve-skill").exists()


def test_promoted_skill_is_recalled_on_next_run(tmp_path):
    """A promoted (enabled:true) skill is loadable via skills._parse on the next run."""
    from argos.skills import _parse

    tasks = [_make_task("t1")]
    cand = _make_candidate("recall-skill")

    result = promotion_gate.promote(
        candidate=cand,
        tasks=tasks,
        runner=_FailRunner(),
        runner_b=_PassRunner(),
        skills_root=tmp_path / "skills",
    )

    assert result.promoted is True

    # Parse the on-disk file the same way load_all() would on next run
    skill_md_path = tmp_path / "skills" / "recall-skill" / "SKILL.md"
    skill = _parse(skill_md_path)
    assert skill is not None, "SKILL.md should be parseable"
    assert skill.enabled is True, "promoted skill should be enabled=True (auto-enable)"


def test_enable_in_body_only_touches_frontmatter():
    """_enable_in_body must not rewrite 'enabled: false' in the skill body text."""
    body = (
        "---\n"
        "name: test\n"
        "enabled: false\n"
        "---\n\n"
        "Use when `enabled: false` is the right config.\n"
    )
    result = promotion_gate._enable_in_body(body)
    lines = result.splitlines()
    # Frontmatter line flipped
    assert "enabled: true" in result
    # Body prose unchanged
    assert "Use when `enabled: false` is the right config." in result
