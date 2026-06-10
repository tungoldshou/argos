"""E4 self_verified firewall 验收 —— 防 self_verified=True 漏进用户级"passed"判断
(尤其 Dreaming/B1 skill promotion 链路)。

不变量(契约 §6.1 + spec §12.5):
  · self_verified=True 的 passed **绝不** 等同于用户级 passed。
  · Verdict.is_user_verified 是用户级 passed 单一信源。
  · 学习链路(hook.distill / hook.promote)只看 is_user_verified 决定是否触发。

覆盖三类断言(用户给的 acceptance):
  (a) self_verified=True 的 passed 【不】触发 distill 或 promote
  (b) 所有用户级 pass 谓词对 self_verified=True 返 False
  (c) 正常用户级 passed 行为不变(distill+promote 照常调)
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from argos_agent.core.types import Verdict
from argos_agent.learning import hook


# ── helpers ────────────────────────────────────────────────


def _write_run_store(tmp_path: Path, run_id: str, events: list[dict]) -> None:
    runs_dir = tmp_path / "runs"
    runs_dir.mkdir(parents=True, exist_ok=True)
    p = runs_dir / f"{run_id}.jsonl"
    with p.open("w", encoding="utf-8") as fh:
        for ev in events:
            fh.write(json.dumps(ev, ensure_ascii=False) + "\n")


def _user_passed_events(verify_cmd: str = "pytest -q") -> list[dict]:
    """用户级 verify passed(self_verified=False)轨迹。"""
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
    """自验证 passed(self_verified=True)轨迹 —— 这是防火墙要拦的。"""
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


# ── (b) Verdict.is_user_verified 谓词是用户级 passed 单一信源 ────


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
        """self_verified 是独立旗标,status 仍 'passed' —— 但 is_user_verified 必须 False。
        这是防火墙核心:不能让 status=='passed' 的 caller 误判为用户级。"""
        v = Verdict.passed_self("ok", "pytest -q", 1)
        assert v.status == "passed"
        assert v.self_verified is True
        assert v.is_user_verified is False

    def test_user_passed_self_verified_flag_default_false(self):
        """Verdict.passed(...) 工厂必须 self_verified=False(默认)。"""
        v = Verdict.passed("ok", "pytest -q", 1)
        assert v.self_verified is False


# ── (a) self_verified=True 【不】触发 distill / promote ────


@pytest.mark.asyncio
async def test_self_verified_passed_does_not_trigger_distill(tmp_path, monkeypatch):
    """self_verified=True 的 passed → hook 走 reflection(distill/promote 都不调)。

    这是 reward-hacking 死亡螺旋的防火墙:agent 不能从"自己造自己跑过的测试"里蒸馏技能。
    """
    from argos_agent.learning import distiller, promotion_gate, reflection

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
        self_verified=True,                 # ← 防火墙关键形参
        skills_root=tmp_path / "skills",
        runner_factory=lambda: None,
        tasks=[object()],
    )

    assert len(distill_calls) == 0, "self_verified 不得触发 distill"
    assert len(promote_calls) == 0, "self_verified 不得触发 promote"
    # 走 reflection(self_verified 视为"非用户级通过",不产生新技能)
    assert len(reflect_calls) == 1, "self_verified 应降级为 reflection"


@pytest.mark.asyncio
async def test_self_verified_default_false_is_backward_compatible(tmp_path, monkeypatch):
    """on_run_completed 不传 self_verified 时,默认 False(保留旧调用方契约)。"""
    from argos_agent.learning import distiller, promotion_gate

    distill_calls: list[dict] = []
    promote_calls: list[dict] = []

    def _distill_stub(**kw):
        distill_calls.append(kw)
        from argos_agent.learning.distiller import SkillCandidate
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
        # self_verified 故意不传 → 默认 False
        skills_root=tmp_path / "skills",
        runner_factory=lambda: None,
        tasks=[object()],
    )
    assert len(distill_calls) == 1, "不传 self_verified → 默认用户级 → 应触发 distill"
    assert len(promote_calls) == 1


# ── (c) 正常用户级 passed 行为不变(distill+promote 照常) ────


@pytest.mark.asyncio
async def test_user_verified_passed_still_triggers_distill_and_promote(tmp_path, monkeypatch):
    """self_verified=False(用户级)passed → distill + promote 都跑(回归测试)。"""
    from argos_agent.learning import distiller, promotion_gate

    distill_calls: list[dict] = []
    promote_calls: list[dict] = []

    def _distill_stub(**kw):
        distill_calls.append(kw)
        from argos_agent.learning.distiller import SkillCandidate
        return SkillCandidate(
            name="user-skill", body_markdown="# b\n", verify_cmd="pytest -q",
            skill_md_path=tmp_path / "skills" / "user-skill" / "SKILL.md",
        )

    def _promote_stub(candidate, **kw):
        promote_calls.append({"name": candidate.name, **kw})
        from argos_agent.learning.promotion_gate import PromotionResult
        return PromotionResult(promoted=False, reason="stubbed")

    monkeypatch.setattr(distiller, "distill_run_to_skill", _distill_stub)
    monkeypatch.setattr(promotion_gate, "promote", _promote_stub)

    run_id = "r#user-verified"
    _write_run_store(tmp_path, run_id, _user_passed_events())

    await hook.on_run_completed(
        run_id=run_id, store_dir=tmp_path / "runs",
        goal="x", verify_cmd="pytest -q",
        verdict_status="passed",
        self_verified=False,                 # ← 显式 False
        skills_root=tmp_path / "skills",
        runner_factory=lambda: None,
        tasks=[object()],
    )
    assert len(distill_calls) == 1
    assert len(promote_calls) == 1


@pytest.mark.asyncio
async def test_failed_run_path_unchanged(tmp_path, monkeypatch):
    """failed 路径(self_verified 任意)只走 reflection,不动 distill/promote。"""
    from argos_agent.learning import distiller, promotion_gate, reflection

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
