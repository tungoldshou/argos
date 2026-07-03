"""Internal documentation."""
from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from pathlib import Path

import pytest

from argos.learning import dream
from argos.learning.candidates import (
    list_unconsumed, save_candidate,
)
from argos.learning.distiller import SkillCandidate


# ── fake runner ───────────────────────────────────────────────────────────────

@dataclass
class _FakeResult:
    """Internal documentation."""
    pass_status: str


class _PassRunner:
    """Internal documentation."""
    def run(self, task, *, model_tier: str):
        return _FakeResult(pass_status="passed")


class _FailRunner:
    """Internal documentation."""
    def run(self, task, *, model_tier: str):
        return _FakeResult(pass_status="failed")


class _SlowPassRunner:
    """Internal documentation."""
    def run(self, task, *, model_tier: str):
        import time
        time.sleep(0.05)
        return _FakeResult(pass_status="passed")



def _seed_candidate(
    root: Path, *, run: str, goal: str, workspace: str | None,
    verify_cmd: str | None = "true", body: str = "",
) -> Path:
    """Internal documentation."""
    cand = SkillCandidate(
        name="learned",
        body_markdown=body or f"# {goal}\n\n```python\nprint('ok')\n```",
        verify_cmd=verify_cmd,
        skill_md_path=Path("unused"),
    )
    p = save_candidate(
        cand, root=root, source_run=run, workspace=workspace, goal=goal,
    )
    assert p is not None
    return p


def _read_consumed_reason(cand_dir: Path) -> str | None:
    meta = json.loads((cand_dir / "meta.json").read_text(encoding="utf-8"))
    return meta.get("consumed_reason")


def _make_pipeline(tmp_path: Path, runner_factory, **kw) -> tuple:
    """Internal documentation."""
    events: list[dict] = []

    def _broadcast(payload: dict) -> None:
        events.append(payload)

    pipe = dream.DreamPipeline(
        candidates_root=tmp_path / "candidates",
        skills_root=tmp_path / "skills",
        memory_dir=tmp_path / "memory",
        dreams_dir=tmp_path / "dreams",
        runner_factory=runner_factory,
        broadcast_fn=_broadcast,
        **kw,
    )
    return pipe, events



def test_pipeline_promotes_and_consumes_on_improvement(tmp_path: Path):
    """Internal documentation."""
    cand_root = tmp_path / "candidates"
    ws = tmp_path / "ws"
    ws.mkdir()
    _seed_candidate(cand_root, run="run0001aaaa11", goal="fix login auth bug",
                    workspace=str(ws), verify_cmd="true")
    _seed_candidate(cand_root, run="run0002bbbb22", goal="fix login auth timeout bug",
                    workspace=str(ws), verify_cmd="true")

    def factory(hint):
        return _PassRunner() if hint else _FailRunner()

    pipe, events = _make_pipeline(tmp_path, factory)
    report = asyncio.run(pipe.run())

    assert report is not None
    assert report.units_total == 1
    assert report.promoted == 1
    skill_mds = list((tmp_path / "skills").glob("*/SKILL.md"))
    assert len(skill_mds) == 1
    assert list_unconsumed(cand_root) == []
    kinds = {e["kind"] for e in events}
    assert "dream_progress" in kinds
    assert "dream_report" in kinds
    stages = {e.get("stage") for e in events if e["kind"] == "dream_progress"}
    assert "done" in stages, f"done 阶段必须 emit;实得 stages={stages}"
    dream_files = list((tmp_path / "dreams").glob("*.jsonl"))
    assert len(dream_files) == 1
    assert report.report_path == str(dream_files[0])


# ── test 2: workspace_gone ────────────────────────────────────────────────────

def test_pipeline_workspace_gone_consumes(tmp_path: Path):
    """Internal documentation."""
    cand_root = tmp_path / "candidates"
    cand_dir = _seed_candidate(cand_root, run="gone0001aaaa", goal="孤儿任务",
                               workspace=None, verify_cmd="true")

    pipe, events = _make_pipeline(tmp_path, lambda hint: _PassRunner())
    report = asyncio.run(pipe.run())

    assert report is not None
    assert report.promoted == 0
    assert list((tmp_path / "skills").glob("*/SKILL.md")) == []
    assert list_unconsumed(cand_root) == []
    assert _read_consumed_reason(cand_dir) == "workspace_gone"



def test_pipeline_single_flight(tmp_path: Path):
    """Internal documentation."""
    cand_root = tmp_path / "candidates"
    ws = tmp_path / "ws"
    ws.mkdir()
    _seed_candidate(cand_root, run="slow0001aaaa", goal="慢任务整合",
                    workspace=str(ws), verify_cmd="true")

    def factory(hint):
        return _SlowPassRunner() if hint else _FailRunner()

    pipe, _events = _make_pipeline(tmp_path, factory)

    async def _both():
        return await asyncio.gather(pipe.run(), pipe.run())

    results = asyncio.run(_both())
    nones = [r for r in results if r is None]
    assert len(nones) == 1



def test_pipeline_holds_over_truncated_sources(tmp_path: Path):
    """Internal documentation."""
    cand_root = tmp_path / "candidates"
    ws = tmp_path / "ws"
    ws.mkdir()
    for i in range(7):
        _seed_candidate(
            cand_root, run=f"hold{i:04d}xxxx",
            goal=f"fix login auth bug attempt {i}",
            workspace=str(ws), verify_cmd="true",
        )

    def factory(hint):
        return _PassRunner() if hint else _FailRunner()

    pipe, _events = _make_pipeline(tmp_path, factory)
    report = asyncio.run(pipe.run())

    assert report is not None
    assert report.units_total == 1
    assert report.promoted == 1
    remaining = list_unconsumed(cand_root)
    assert len(remaining) == 2



def test_pipeline_name_collision_consumes_sources(tmp_path: Path, monkeypatch):
    """Internal documentation."""
    import asyncio as _asyncio
    from unittest.mock import patch

    from argos.learning.promotion_gate import PromotionResult

    cand_root = tmp_path / "candidates"
    ws = tmp_path / "ws"
    ws.mkdir()
    cand_dir = _seed_candidate(
        cand_root, run="coll0001aaaa", goal="fix login auth bug",
        workspace=str(ws), verify_cmd="true",
    )

    collision_result = PromotionResult(promoted=False, reason="name_collision:fix-login-auth-bug")

    with patch("argos.learning.promotion_gate.promote", return_value=collision_result):
        pipe, _events = _make_pipeline(tmp_path, lambda hint: _PassRunner())
        report = _asyncio.run(pipe.run())

    assert report is not None
    assert report.promoted == 0
    assert report.skipped == 1
    remaining = list_unconsumed(cand_root)
    assert remaining == [], f"期望队列清空,实际: {remaining}"
    assert _read_consumed_reason(cand_dir) == "name_collision"



def test_pipeline_rejected_ab_consumes_with_reason(tmp_path: Path):
    """Internal documentation."""
    cand_root = tmp_path / "candidates"
    ws = tmp_path / "ws"
    ws.mkdir()
    cand_dir1 = _seed_candidate(
        cand_root, run="rab10001aaaa", goal="fix login auth bug",
        workspace=str(ws), verify_cmd="true",
    )
    cand_dir2 = _seed_candidate(
        cand_root, run="rab20002bbbb", goal="fix login auth timeout bug",
        workspace=str(ws), verify_cmd="true",
    )

    # → a_passed == b_passed → b_passed <= a_passed → no_improvement → rejected_ab
    pipe, events = _make_pipeline(tmp_path, lambda hint: _PassRunner())
    report = asyncio.run(pipe.run())

    assert report is not None
    assert report.rejected == 1, (
        f"期望 rejected==1,实得 {report.rejected};"
        " 可能 no_improvement 分支漏计数"
    )
    assert report.promoted == 0
    remaining = list_unconsumed(cand_root)
    assert remaining == [], (
        f"期望候选区清空,实际 unconsumed={remaining};"
        " 可能 mark_consumed 未被调用"
    )
    reason1 = _read_consumed_reason(cand_dir1)
    reason2 = _read_consumed_reason(cand_dir2)
    assert reason1 == "rejected_ab", (
        f"cand1 consumed_reason={reason1!r},期望 'rejected_ab'"
    )
    assert reason2 == "rejected_ab", (
        f"cand2 consumed_reason={reason2!r},期望 'rejected_ab'"
    )



def test_emit_handles_async_broadcast_fn(tmp_path: Path):
    """Internal documentation."""
    cand_root = tmp_path / "candidates"
    ws = tmp_path / "ws"
    ws.mkdir()
    _seed_candidate(cand_root, run="async0001aaaa", goal="fix login auth bug",
                    workspace=str(ws), verify_cmd="true")
    _seed_candidate(cand_root, run="async0002bbbb", goal="fix login auth timeout bug",
                    workspace=str(ws), verify_cmd="true")

    collected: list[dict] = []

    async def _async_broadcast(payload: dict) -> None:
        """Internal documentation."""
        collected.append(payload)

    pipe = dream.DreamPipeline(
        candidates_root=cand_root,
        skills_root=tmp_path / "skills",
        memory_dir=tmp_path / "memory",
        dreams_dir=tmp_path / "dreams",
        runner_factory=lambda hint: _PassRunner() if hint else _FailRunner(),
        broadcast_fn=_async_broadcast,
    )

    async def _run():
        return await pipe.run()

    report = asyncio.run(_run())
    assert report is not None, "pipeline 应返回 DreamReport"
    kinds = {e["kind"] for e in collected}
    assert "dream_report" in kinds, (
        f"async broadcast_fn 的事件被静默丢弃; collected={collected}"
    )
