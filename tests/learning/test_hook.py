"""learning hook 验收 — 任务:对主任务无副作用,后台跑,失败降级。"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from argos_agent.learning import hook


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

    from argos_agent.learning import distiller, promotion_gate

    def _distill_stub(**kw):
        distill_calls.append(kw)
        from argos_agent.learning.distiller import SkillCandidate
        return SkillCandidate(
            name="stub-skill", body_markdown="# body\n", verify_cmd="pytest",
            skill_md_path=tmp_path / "skills" / "stub-skill" / "SKILL.md",
        )
    def _promote_stub(candidate, **kw):
        promote_calls.append({"name": candidate.name, **kw})
        from argos_agent.learning.promotion_gate import PromotionResult
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

    from argos_agent.learning import distiller, promotion_gate, reflection

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
    from argos_agent.learning import distiller, promotion_gate

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
