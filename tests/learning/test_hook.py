"""learning hook 验收 — 任务:对主任务无副作用,后台跑,失败降级。"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from argos.learning import hook


def _write_run_store(tmp_path: Path, run_id: str, events: list[dict]) -> None:
    runs_dir = tmp_path / "runs"
    runs_dir.mkdir(parents=True, exist_ok=True)
    p = runs_dir / f"{run_id}.jsonl"
    with p.open("w", encoding="utf-8") as fh:
        for ev in events:
            fh.write(json.dumps(ev, ensure_ascii=False) + "\n")


def _passed_events(verify_cmd: str = "pytest -q") -> list[dict]:
    return [
        {"kind": "session_start", "goal": "fix foo", "seq": 0},
        {"kind": "code_action", "code": "x = 1", "step": 0, "seq": 1},
        {"kind": "code_result", "stdout": "ok", "value_repr": "None", "exc": "", "ok": True, "step": 0, "seq": 2},
        {"kind": "verify_verdict",
         "verdict": {"status": "passed", "reason": "ok", "verify_cmd": verify_cmd},
         "seq": 3},
    ]


def _failed_events() -> list[dict]:
    return [
        {"kind": "session_start", "goal": "fix foo", "seq": 0},
        {"kind": "code_action", "code": "x = 1", "step": 0, "seq": 1},
        {"kind": "verify_verdict",
         "verdict": {"status": "failed", "reason": "AssertionError", "verify_cmd": "pytest"},
         "seq": 2},
    ]


# ── 验收 d: 整个过程对主任务无副作用 ────────────────────
@pytest.mark.asyncio
async def test_passed_run_triggers_distill_and_promote(tmp_path, monkeypatch):
    """passed → distill + promotion_gate 都跑(monkeypatch 看到调用)。

    tasks 传一个 placeholder(让 hook 走到 promote 分支);promote 本身被 stub,不真评估。
    """
    distill_calls: list[dict] = []
    promote_calls: list[dict] = []

    from argos.learning import distiller, promotion_gate

    def _distill_stub(**kw):
        distill_calls.append(kw)
        from argos.learning.distiller import SkillCandidate
        return SkillCandidate(
            name="stub-skill", body_markdown="# body\n", verify_cmd="pytest",
            skill_md_path=tmp_path / "skills" / "stub-skill" / "SKILL.md",
        )
    def _promote_stub(candidate, **kw):
        promote_calls.append({"name": candidate.name, **kw})
        from argos.learning.promotion_gate import PromotionResult
        return PromotionResult(promoted=False, reason="stubbed")

    monkeypatch.setattr(distiller, "distill_run_to_skill", _distill_stub)
    monkeypatch.setattr(promotion_gate, "promote", _promote_stub)

    run_id = "r#passed"
    _write_run_store(tmp_path, run_id, _passed_events())

    # tasks 传一个 placeholder 对象;promote 被 stub,不读字段
    placeholder_tasks = [object()]

    await hook.on_run_completed(
        run_id=run_id, store_dir=tmp_path / "runs",
        goal="fix foo", verify_cmd="pytest -q",
        verdict_status="passed",
        skills_root=tmp_path / "skills",
        runner_factory=lambda: None,
        tasks=placeholder_tasks,
    )
    assert len(distill_calls) == 1
    assert len(promote_calls) == 1
    assert promote_calls[0]["name"] == "stub-skill"


@pytest.mark.asyncio
async def test_failed_run_triggers_reflection_only(tmp_path, monkeypatch):
    """failed → reflection 调 + distill【不】调 + promote【不】调。"""
    reflect_calls: list[dict] = []
    distill_calls: list[dict] = []
    promote_calls: list[dict] = []

    from argos.learning import distiller, promotion_gate, reflection

    monkeypatch.setattr(
        reflection, "reflect_failure",
        lambda **kw: reflect_calls.append(kw),
    )
    def _distill_stub(**kw):
        distill_calls.append(kw)
        return None
    def _promote_stub(**kw):
        promote_calls.append(kw)
    monkeypatch.setattr(distiller, "distill_run_to_skill", _distill_stub)
    monkeypatch.setattr(promotion_gate, "promote", _promote_stub)

    run_id = "r#failed"
    _write_run_store(tmp_path, run_id, _failed_events())

    await hook.on_run_completed(
        run_id=run_id, store_dir=tmp_path / "runs",
        goal="fix foo", verify_cmd="pytest",
        verdict_status="failed",
        skills_root=tmp_path / "skills",
        runner_factory=lambda: None,
        tasks=[],
    )
    assert len(reflect_calls) == 1
    assert len(distill_calls) == 0
    assert len(promote_calls) == 0


@pytest.mark.asyncio
async def test_hook_swallows_distill_exceptions(tmp_path, monkeypatch):
    """distill 抛异常 → on_run_completed 不抛(caller 放心 await)。"""
    from argos.learning import distiller, promotion_gate

    def _boom(**kw):
        raise RuntimeError("distill failed")
    monkeypatch.setattr(distiller, "distill_run_to_skill", _boom)
    monkeypatch.setattr(promotion_gate, "promote", lambda **kw: None)

    run_id = "r#boom"
    _write_run_store(tmp_path, run_id, _passed_events())
    # 不抛
    await hook.on_run_completed(
        run_id=run_id, store_dir=tmp_path / "runs",
        goal="x", verify_cmd="pytest -q",
        verdict_status="passed",
        skills_root=tmp_path / "skills",
        runner_factory=lambda: None,
        tasks=[object()],
    )


@pytest.mark.asyncio
async def test_hook_does_not_modify_store_events(tmp_path):
    """主 run 的 store 文件内容不被 hook 改动(append-only 假设)。"""
    run_id = "r#no-touch"
    _write_run_store(tmp_path, run_id, _passed_events())
    p = tmp_path / "runs" / f"{run_id}.jsonl"
    before = p.read_text(encoding="utf-8")

    await hook.on_run_completed(
        run_id=run_id, store_dir=tmp_path / "runs",
        goal="x", verify_cmd="pytest -q",
        verdict_status="passed",
        skills_root=tmp_path / "skills",
        runner_factory=lambda: None,
        tasks=[object()],
    )
    after = p.read_text(encoding="utf-8")
    assert before == after, "hook 不得修改主 run 的 store"


@pytest.mark.asyncio
async def test_hook_is_awaitable_and_returns_none(tmp_path):
    """hook 是 async 函数,返 None(caller 不依赖返回值)。"""
    run_id = "r#await"
    _write_run_store(tmp_path, run_id, _passed_events())
    result = await hook.on_run_completed(
        run_id=run_id, store_dir=tmp_path / "runs",
        goal="x", verify_cmd="pytest -q",
        verdict_status="passed",
        skills_root=tmp_path / "skills",
        runner_factory=lambda: None,
        tasks=[object()],
    )
    assert result is None


# ── Task 3:无 runner 时候选落盘(修复:候选丢弃断电) ─────────────────────────────


def test_passed_without_runner_persists_candidate(tmp_path, monkeypatch):
    """无 runner 时候选必须落盘(修复:当场丢弃)。

    评审 I2:monkeypatch distiller 返回固定候选,解耦 distiller 内部行为
    (hook 内 `from ... import distiller` 后调模块属性,patch 可拦截)。
    """
    store_dir = tmp_path / "runs"
    store_dir.mkdir()
    run_id = "abc123def456"
    # store 文件需存在,内容随意(distill 已被 stub,不读它)
    (store_dir / f"{run_id}.jsonl").write_text(
        json.dumps({"kind": "run_meta", "run_id": run_id}), encoding="utf-8")

    from argos.learning import distiller
    from argos.learning.distiller import SkillCandidate

    monkeypatch.setattr(
        distiller, "distill_run_to_skill",
        lambda **kw: SkillCandidate(
            name="fix-login", body_markdown="# body\n",
            verify_cmd="pytest -q", skill_md_path=Path("u"),
        ),
    )

    from argos.learning.hook import on_run_completed
    asyncio.run(on_run_completed(
        run_id=run_id, store_dir=store_dir, goal="say hello",
        verify_cmd="pytest -q", verdict_status="passed",
        skills_root=tmp_path / "skills",
        candidates_root=tmp_path / "candidates",
        workspace="/tmp/proj",
        runner_factory=None, tasks=[],
    ))
    from argos.learning.candidates import list_unconsumed
    got = list_unconsumed(tmp_path / "candidates")
    assert len(got) == 1
    assert got[0].workspace == "/tmp/proj"
    assert got[0].verify_cmd == "pytest -q"


# ── Real-gate A/B promotion tests (no promote mock) ─────────────────────────
# These tests drive the ACTUAL promotion_gate.promote() — not a stub — so they
# catch the degenerate A==B bug (where A and B share the same unhinted runner).
#
# Stub runner design: _StubRunner.run() checks whether the task goal contains
# the hinted prefix injected by HintedRunner; B-hinted tasks will have it,
# A-bare tasks won't.  This lets us assert that HintedRunner is actually being
# used, not just that some runner_b was passed.

def _make_eval_result(task, pass_status: str):
    from argos.eval.runner import EvalResult
    return EvalResult(
        task_id=task.id, run_id="stub", model_tier="default",
        started_at=0.0, finished_at=0.0, duration_s=0.0,
        pass_status=pass_status, verify_cmd=task.verify_cmd,
        verify_detail="stub", tampered=(), tokens_in=0, tokens_out=0,
        cost_usd=None, steps=1, worktree_path="", isolation_fallback=None,
        error=None, corpus_version=0, goal=task.goal,
    )


class _BarePassRunner:
    """Always returns 'passed'."""
    def run(self, task, *, model_tier: str):
        return _make_eval_result(task, "passed")


class _BareFailRunner:
    """Always returns 'failed'."""
    def run(self, task, *, model_tier: str):
        return _make_eval_result(task, "failed")


def _make_task_for_gate(tmp_path):
    from argos.eval.corpus import EvalTask
    return EvalTask(
        id="gate-t1", category="self_check", difficulty="easy",
        title="gate task", goal="do something", verify_cmd="true",
        setup_cmd=None, expected_files=(), working_dir=tmp_path,
        corpus_version=0,
    )


def _make_distilled_candidate(name: str, skills_root):
    from argos.learning.distiller import SkillCandidate
    return SkillCandidate(
        name=name, body_markdown="# Skill body\nDo the thing.\n",
        verify_cmd="true",
        skill_md_path=skills_root / name / "SKILL.md",
    )


@pytest.mark.asyncio
async def test_real_promote_no_improvement_no_skill_written(tmp_path, monkeypatch):
    """Real gate: A-bare=passed, B-hinted=passed (equal) → no improvement → skill NOT written.

    Drives the actual promotion_gate.promote() — promote is NOT patched.
    """
    skills_root = tmp_path / "skills"
    store_dir = tmp_path / "runs"
    store_dir.mkdir()
    run_id = "gate-no-improve"
    (store_dir / f"{run_id}.jsonl").write_text(
        json.dumps({"kind": "code_action", "code": "x=1"}), encoding="utf-8")

    cand_name = "gate-learned-skill"
    cand = _make_distilled_candidate(cand_name, skills_root)

    from argos.learning import distiller as distiller_mod
    monkeypatch.setattr(distiller_mod, "distill_run_to_skill", lambda **kw: cand)

    task = _make_task_for_gate(tmp_path)
    # A=passed, B=passed → b_passed (1) == a_passed (1) → no_improvement
    # Since HintedRunner wraps inner, and inner is _BarePassRunner, both A and B pass.
    # promote() sees b_passed <= a_passed → no skill file.
    bare_runner = _BarePassRunner()

    from argos.learning.hook import on_run_completed
    await on_run_completed(
        run_id=run_id, store_dir=store_dir,
        goal="do something", verify_cmd="true",
        verdict_status="passed",
        skills_root=skills_root,
        runner_factory=lambda: bare_runner,
        tasks=[task],
    )

    # Skill file must NOT be written when B offers no improvement over A
    skill_path = skills_root / cand_name / "SKILL.md"
    assert not skill_path.exists(), (
        f"Skill was written despite no improvement — degenerate A==B bug is back: {skill_path}"
    )


@pytest.mark.asyncio
async def test_real_promote_b_wins_skill_written(tmp_path, monkeypatch):
    """Real gate: A-bare=failed, B-hinted=passed → B wins → skill IS written.

    Drives the actual promotion_gate.promote() — promote is NOT patched.
    HintedRunner wraps the inner runner; A side calls inner directly (fails),
    B side calls inner via HintedRunner (also hits inner, but we give it a
    'passed' runner to simulate the hint genuinely helping).
    """
    skills_root = tmp_path / "skills"
    store_dir = tmp_path / "runs"
    store_dir.mkdir()
    run_id = "gate-b-wins"
    (store_dir / f"{run_id}.jsonl").write_text(
        json.dumps({"kind": "code_action", "code": "x=1"}), encoding="utf-8")

    cand_name = "gate-better-skill"
    cand = _make_distilled_candidate(cand_name, skills_root)

    from argos.learning import distiller as distiller_mod
    monkeypatch.setattr(distiller_mod, "distill_run_to_skill", lambda **kw: cand)

    task = _make_task_for_gate(tmp_path)

    # A=bare runner that always fails; B=HintedRunner wrapping a passing inner runner.
    # hook._on_passed builds runner_b=HintedRunner(inner=runner, hint=cand.body_markdown)
    # where runner=runner_factory() = _BareFailRunner().
    # BUT: promotion_gate.promote calls runner.run (A-bare → fails) then runner_b.run
    # (B-hinted → wraps the same _BareFailRunner... also fails).
    #
    # To test that B genuinely wins we need the B-side runner_factory to supply a
    # *passing* inner runner.  We achieve this by giving runner_factory a counter:
    # first call (A) → _BareFailRunner, second call never happens (hook builds runner_b
    # from the already-created runner).  So instead we supply a runner whose .run()
    # checks for the HintedRunner hint prefix in task.goal and passes only when hinted.

    class _HintSensitiveRunner:
        """Passes only when the task goal contains the HintedRunner prefix."""
        def run(self, task, *, model_tier: str):
            from argos.i18n import t
            prefix = t("learn.dream.hinted_runner_prefix")
            if prefix and prefix in task.goal:
                return _make_eval_result(task, "passed")
            return _make_eval_result(task, "failed")

    hint_sensitive = _HintSensitiveRunner()

    from argos.learning.hook import on_run_completed
    await on_run_completed(
        run_id=run_id, store_dir=store_dir,
        goal="do something", verify_cmd="true",
        verdict_status="passed",
        skills_root=skills_root,
        runner_factory=lambda: hint_sensitive,
        tasks=[task],
    )

    # Skill file MUST be written when B-hinted passes and A-bare fails
    skill_path = skills_root / cand_name / "SKILL.md"
    assert skill_path.exists(), (
        f"Skill was NOT written even though B-hinted passed and A-bare failed; "
        f"HintedRunner may not be wired into hook._on_passed"
    )


def test_self_verified_passed_never_calls_save_candidate(tmp_path, monkeypatch):
    """E4 防火墙(评审 B1 加固):不只断言候选区为空(那会因路由本来就不
    落盘而平凡通过),用 spy 钉死 save_candidate 在 self_verified 路径上
    从未被调用 —— 防火墙断在调用层,不是碰巧没产物。"""
    store_dir = tmp_path / "runs"
    store_dir.mkdir()
    run_id = "abc123def456"
    (store_dir / f"{run_id}.jsonl").write_text(
        json.dumps({"kind": "code_action", "code": "x=1"}), encoding="utf-8")

    calls: list = []
    from argos.learning import candidates as cands_mod
    real_save = cands_mod.save_candidate
    monkeypatch.setattr(cands_mod, "save_candidate",
                        lambda *a, **kw: calls.append(kw) or real_save(*a, **kw))

    from argos.learning.hook import on_run_completed
    asyncio.run(on_run_completed(
        run_id=run_id, store_dir=store_dir, goal="g",
        verify_cmd="pytest -q", verdict_status="passed", self_verified=True,
        skills_root=tmp_path / "skills",
        candidates_root=tmp_path / "candidates",
        runner_factory=None, tasks=[],
    ))
    assert calls == []                                     # 调用层防线
    from argos.learning.candidates import list_unconsumed
    assert list_unconsumed(tmp_path / "candidates") == []  # 产物层防线
