"""Task 8: DreamPipeline 编排验收(TDD)。

覆盖:
1. 提升路径:相似候选综合 → B>A → 晋升 + 源被消费 + 事件 + 报告落盘
2. workspace_gone:证据拿不到 → 不晋升但消费(防夜夜重复)
3. 单飞:已锁 → 第二次调用返 None
4. 留宿契约:超大簇截取 5 源,留宿 2 源仍 unconsumed

fake runner 只需 .run(task, *, model_tier) → 带 pass_status 属性的对象。
"""
from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from pathlib import Path

import pytest

from argos_agent.learning import dream
from argos_agent.learning.candidates import (
    list_unconsumed, save_candidate,
)
from argos_agent.learning.distiller import SkillCandidate


# ── fake runner ───────────────────────────────────────────────────────────────

@dataclass
class _FakeResult:
    """EvalResult-look-alike:promote 只读 pass_status。"""
    pass_status: str


class _PassRunner:
    """每个 task 都 passed。"""
    def run(self, task, *, model_tier: str):
        return _FakeResult(pass_status="passed")


class _FailRunner:
    """每个 task 都 failed(A 侧用 → B>A 成立)。"""
    def run(self, task, *, model_tier: str):
        return _FakeResult(pass_status="failed")


class _SlowPassRunner:
    """慢 passed runner(单飞测试用:让两次 run() 真正并发竞争锁)。"""
    def run(self, task, *, model_tier: str):
        import time
        time.sleep(0.05)
        return _FakeResult(pass_status="passed")


# ── helper:种候选 ─────────────────────────────────────────────────────────────

def _seed_candidate(
    root: Path, *, run: str, goal: str, workspace: str | None,
    verify_cmd: str | None = "true", body: str = "",
) -> Path:
    """落一个候选到候选区。返回候选目录。"""
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
    """构造 DreamPipeline + 事件收集器。返回 (pipeline, events)。"""
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


# ── test 1: 提升 + 消费 ───────────────────────────────────────────────────────

def test_pipeline_promotes_and_consumes_on_improvement(tmp_path: Path):
    """2 个相似候选(真 workspace)+ B>A runner → 晋升 1 个、源全消费、事件齐、报告落盘。"""
    cand_root = tmp_path / "candidates"
    ws = tmp_path / "ws"
    ws.mkdir()
    _seed_candidate(cand_root, run="run0001aaaa11", goal="fix login auth bug",
                    workspace=str(ws), verify_cmd="true")
    _seed_candidate(cand_root, run="run0002bbbb22", goal="fix login auth timeout bug",
                    workspace=str(ws), verify_cmd="true")

    # B 侧(hint 非空)passed,A 侧(hint=None)failed → B>A
    def factory(hint):
        return _PassRunner() if hint else _FailRunner()

    pipe, events = _make_pipeline(tmp_path, factory)
    report = asyncio.run(pipe.run())

    assert report is not None
    assert report.units_total == 1            # 2 相似 → 1 综合单元
    assert report.promoted == 1
    # 晋升产物落盘
    skill_mds = list((tmp_path / "skills").glob("*/SKILL.md"))
    assert len(skill_mds) == 1
    # 源全消费(候选区清空)
    assert list_unconsumed(cand_root) == []
    # 事件:有 dream_progress 和 dream_report
    kinds = {e["kind"] for e in events}
    assert "dream_progress" in kinds
    assert "dream_report" in kinds
    # 报告落盘:dreams 目录有 .jsonl
    dream_files = list((tmp_path / "dreams").glob("*.jsonl"))
    assert len(dream_files) == 1
    assert report.report_path == str(dream_files[0])


# ── test 2: workspace_gone ────────────────────────────────────────────────────

def test_pipeline_workspace_gone_consumes(tmp_path: Path):
    """workspace=None 的候选 → 不晋升、无产物、但被 consumed(reason=workspace_gone)。"""
    cand_root = tmp_path / "candidates"
    cand_dir = _seed_candidate(cand_root, run="gone0001aaaa", goal="孤儿任务",
                               workspace=None, verify_cmd="true")

    pipe, events = _make_pipeline(tmp_path, lambda hint: _PassRunner())
    report = asyncio.run(pipe.run())

    assert report is not None
    assert report.promoted == 0
    # 无晋升产物
    assert list((tmp_path / "skills").glob("*/SKILL.md")) == []
    # 候选已消费(workspace_gone)
    assert list_unconsumed(cand_root) == []
    assert _read_consumed_reason(cand_dir) == "workspace_gone"


# ── test 3: 单飞 ──────────────────────────────────────────────────────────────

def test_pipeline_single_flight(tmp_path: Path):
    """慢 runner + gather 两次 run() → 恰好一次返 None(锁住单飞)。"""
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
    assert len(nones) == 1   # 恰好一次被单飞拒绝


# ── test 4: 留宿契约 ──────────────────────────────────────────────────────────

def test_pipeline_holds_over_truncated_sources(tmp_path: Path):
    """7 个高相似候选(共享主题)→ 恰 5 个源被消费(promoted),2 个留宿仍 unconsumed。"""
    cand_root = tmp_path / "candidates"
    ws = tmp_path / "ws"
    ws.mkdir()
    # 7 个共享 "fix login auth bug" 主题(只差末尾 attempt 数字)→ 同簇;
    # cluster 截 MAX_UNIT_SOURCES=5 源,余 2 留宿。
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
    # 5 个源被消费,2 个留宿仍 unconsumed
    remaining = list_unconsumed(cand_root)
    assert len(remaining) == 2


# ── test 5: name_collision 不产生死循环 ──────────────────────────────────────

def test_pipeline_name_collision_consumes_sources(tmp_path: Path, monkeypatch):
    """promote 返回 name_collision:<name> → live 源被消费(reason=name_collision),
    不留在 unconsumed 队列;防止下晚永久重试的死循环。"""
    import asyncio as _asyncio
    from unittest.mock import patch

    from argos_agent.learning.promotion_gate import PromotionResult

    cand_root = tmp_path / "candidates"
    ws = tmp_path / "ws"
    ws.mkdir()
    cand_dir = _seed_candidate(
        cand_root, run="coll0001aaaa", goal="fix login auth bug",
        workspace=str(ws), verify_cmd="true",
    )

    # promote 永远返回 name_collision:<slug> — 模拟非学习技能同名
    collision_result = PromotionResult(promoted=False, reason="name_collision:fix-login-auth-bug")

    with patch("argos_agent.learning.promotion_gate.promote", return_value=collision_result):
        pipe, _events = _make_pipeline(tmp_path, lambda hint: _PassRunner())
        report = _asyncio.run(pipe.run())

    assert report is not None
    # 没有晋升产物
    assert report.promoted == 0
    # skipped 计数 +1(而非 rejected)
    assert report.skipped == 1
    # 关键:live 源已消费,不留在队列 → 防死循环
    remaining = list_unconsumed(cand_root)
    assert remaining == [], f"期望队列清空,实际: {remaining}"
    assert _read_consumed_reason(cand_dir) == "name_collision"


# ── test 6: async broadcast_fn 不静默丢事件 ──────────────────────────────────

def test_emit_handles_async_broadcast_fn(tmp_path: Path):
    """_emit 传入 async callable 时,返回的 coroutine 须被 create_task 调度,
    而不是静默抛弃 —— 保证 T9 daemon 接线安全。

    验证:DreamPipeline 构造时传入 async broadcast_fn,
    run() 结束后事件列表非空(至少含 dream_report kind)。
    """
    cand_root = tmp_path / "candidates"
    ws = tmp_path / "ws"
    ws.mkdir()
    _seed_candidate(cand_root, run="async0001aaaa", goal="fix login auth bug",
                    workspace=str(ws), verify_cmd="true")
    _seed_candidate(cand_root, run="async0002bbbb", goal="fix login auth timeout bug",
                    workspace=str(ws), verify_cmd="true")

    collected: list[dict] = []

    async def _async_broadcast(payload: dict) -> None:
        """模拟 T9 daemon 的 async fanout 广播。"""
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
