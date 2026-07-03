from __future__ import annotations

import json
from pathlib import Path

import pytest

from argos.core.types import Verdict
from argos.learning import hook


# ── helpers ────────────────────────────────────────────────


def _write_run_store(tmp_path: Path, run_id: str, events: list[dict]) -> None:
    runs_dir = tmp_path / "runs"
    runs_dir.mkdir(parents=True, exist_ok=True)
    p = runs_dir / f"{run_id}.jsonl"
    with p.open("w", encoding="utf-8") as fh:
        for ev in events:
            fh.write(json.dumps(ev, ensure_ascii=False) + "\n")


def _user_passed_events(verify_cmd: str = "pytest -q") -> list[dict]:
    return [
        {"kind": "session_start", "goal": "fix foo", "seq": 0},
        {"kind": "code_action", "code": "x = 1", "step": 0, "seq": 1},
        {"kind": "code_result", "stdout": "ok", "value_repr": "None", "exc": "", "ok": True, "step": 0, "seq": 2},
        {"kind": "verify_verdict",
         "verdict": {"status": "passed", "self_verified": False,
                     "verify_cmd": verify_cmd, "reason": "ok"},
         "seq": 3},
    ]


def _self_passed_events(verify_cmd: str = "pytest -q") -> list[dict]:
    return [
        {"kind": "session_start", "goal": "fix foo", "seq": 0},
        {"kind": "code_action", "code": "x = 1", "step": 0, "seq": 1},
        {"kind": "verify_verdict",
         "verdict": {"status": "passed", "self_verified": True,
                     "verify_cmd": verify_cmd,
                     "reason": "[self_verified] 自造测试通过"},
         "seq": 2},
    ]


def _failed_events() -> list[dict]:
    return [
        {"kind": "session_start", "goal": "fix foo", "seq": 0},
        {"kind": "code_action", "code": "x = 1", "step": 0, "seq": 1},
        {"kind": "verify_verdict",
         "verdict": {"status": "failed", "reason": "AssertionError", "verify_cmd": "pytest"},
         "seq": 2},
    ]




class TestVerdictIsUserVerified:
    def test_user_passed_is_user_verified(self):
        v = Verdict.passed("ok", "pytest -q", 1)
        assert v.is_user_verified is True

    def test_self_passed_is_not_user_verified(self):
        v = Verdict.passed_self("ok", "pytest -q", 1)
        assert v.is_user_verified is False

    def test_failed_is_not_user_verified(self):
        v = Verdict.failed("boom", "pytest -q", 1)
        assert v.is_user_verified is False

    def test_unverifiable_is_not_user_verified(self):
        v = Verdict.unverifiable("can't tell", [], 1)
        assert v.is_user_verified is False

    def test_self_passed_keeps_status_passed(self):
        v = Verdict.passed_self("ok", "pytest -q", 1)
        assert v.status == "passed"
        assert v.self_verified is True
        assert v.is_user_verified is False

    def test_user_passed_self_verified_flag_default_false(self):
        v = Verdict.passed("ok", "pytest -q", 1)
        assert v.self_verified is False




@pytest.mark.asyncio
async def test_self_verified_passed_does_not_trigger_distill(tmp_path, monkeypatch):
    from argos.learning import distiller, promotion_gate, reflection

    distill_calls: list[dict] = []
    promote_calls: list[dict] = []
    reflect_calls: list[dict] = []

    monkeypatch.setattr(distiller, "distill_run_to_skill",
                        lambda **kw: distill_calls.append(kw) or None)
    monkeypatch.setattr(promotion_gate, "promote",
                        lambda **kw: promote_calls.append(kw))
    monkeypatch.setattr(reflection, "reflect_failure",
                        lambda **kw: reflect_calls.append(kw))

    run_id = "r#self-verified"
    _write_run_store(tmp_path, run_id, _self_passed_events())

    await hook.on_run_completed(
        run_id=run_id, store_dir=tmp_path / "runs",
        goal="fix foo", verify_cmd="pytest -q",
        verdict_status="passed",
        self_verified=True,
        skills_root=tmp_path / "skills",
        runner_factory=lambda: None,
        tasks=[object()],
    )

    assert len(distill_calls) == 0, "self_verified 不得触发 distill"
    assert len(promote_calls) == 0, "self_verified 不得触发 promote"
    assert len(reflect_calls) == 1, "self_verified 应降级为 reflection"


@pytest.mark.asyncio
async def test_self_verified_default_false_is_backward_compatible(tmp_path, monkeypatch):
    from argos.learning import distiller, promotion_gate

    distill_calls: list[dict] = []
    promote_calls: list[dict] = []

    def _distill_stub(**kw):
        distill_calls.append(kw)
        from argos.learning.distiller import SkillCandidate
        return SkillCandidate(
            name="s", body_markdown="# b\n", verify_cmd="pytest -q",
            skill_md_path=tmp_path / "skills" / "s" / "SKILL.md",
        )

    monkeypatch.setattr(distiller, "distill_run_to_skill", _distill_stub)
    monkeypatch.setattr(promotion_gate, "promote",
                        lambda **kw: promote_calls.append(kw))

    run_id = "r#compat"
    _write_run_store(tmp_path, run_id, _user_passed_events())

    await hook.on_run_completed(
        run_id=run_id, store_dir=tmp_path / "runs",
        goal="x", verify_cmd="pytest -q",
        verdict_status="passed",
        skills_root=tmp_path / "skills",
        runner_factory=lambda: None,
        tasks=[object()],
    )
    assert len(distill_calls) == 1, "不传 self_verified → 默认用户级 → 应触发 distill"
    assert len(promote_calls) == 1




@pytest.mark.asyncio
async def test_user_verified_passed_still_triggers_distill_and_promote(tmp_path, monkeypatch):
    from argos.learning import distiller, promotion_gate

    distill_calls: list[dict] = []
    promote_calls: list[dict] = []

    def _distill_stub(**kw):
        distill_calls.append(kw)
        from argos.learning.distiller import SkillCandidate
        return SkillCandidate(
            name="user-skill", body_markdown="# b\n", verify_cmd="pytest -q",
            skill_md_path=tmp_path / "skills" / "user-skill" / "SKILL.md",
        )

    def _promote_stub(candidate, **kw):
        promote_calls.append({"name": candidate.name, **kw})
        from argos.learning.promotion_gate import PromotionResult
        return PromotionResult(promoted=False, reason="stubbed")

    monkeypatch.setattr(distiller, "distill_run_to_skill", _distill_stub)
    monkeypatch.setattr(promotion_gate, "promote", _promote_stub)

    run_id = "r#user-verified"
    _write_run_store(tmp_path, run_id, _user_passed_events())

    await hook.on_run_completed(
        run_id=run_id, store_dir=tmp_path / "runs",
        goal="x", verify_cmd="pytest -q",
        verdict_status="passed",
        self_verified=False,
        skills_root=tmp_path / "skills",
        runner_factory=lambda: None,
        tasks=[object()],
    )
    assert len(distill_calls) == 1
    assert len(promote_calls) == 1


@pytest.mark.asyncio
async def test_failed_run_path_unchanged(tmp_path, monkeypatch):
    from argos.learning import distiller, promotion_gate, reflection

    distill_calls: list[dict] = []
    promote_calls: list[dict] = []
    reflect_calls: list[dict] = []

    monkeypatch.setattr(distiller, "distill_run_to_skill",
                        lambda **kw: distill_calls.append(kw) or None)
    monkeypatch.setattr(promotion_gate, "promote",
                        lambda **kw: promote_calls.append(kw))
    monkeypatch.setattr(reflection, "reflect_failure",
                        lambda **kw: reflect_calls.append(kw))

    run_id = "r#failed"
    _write_run_store(tmp_path, run_id, _failed_events())

    await hook.on_run_completed(
        run_id=run_id, store_dir=tmp_path / "runs",
        goal="x", verify_cmd="pytest",
        verdict_status="failed",
        skills_root=tmp_path / "skills",
        runner_factory=lambda: None,
        tasks=[],
    )
    assert len(distill_calls) == 0
    assert len(promote_calls) == 0
    assert len(reflect_calls) == 1
