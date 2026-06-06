"""run_skill 编排测试(spec §2.1 / §2.6 / §3)。"""
from __future__ import annotations

import asyncio
import time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from argos_agent.skills_runtime.analysis import (
    AnalysisSkill,
    AnalysisSkillContext,
    AnalysisSkillResult,
    Finding,
)
from argos_agent.skills_runtime import registry, runner
from argos_agent.skills_runtime.runner import run_skill


@pytest.fixture(autouse=True)
def _clean_registry():
    """每个测试前后清空 registry(隔离)。"""
    registry._reset_registry()
    yield
    registry._reset_registry()


def _make_ctx(approval_level: str = "auto") -> AnalysisSkillContext:
    return AnalysisSkillContext(
        workspace=Path("/tmp"),
        approval_level=approval_level,
        run_id="test-run-1",
    )


def _register_skill(name: str, *, requires_approval: bool = False, run=None):
    """注册一个默认返 passed 的 skill,允许覆盖 run。"""
    async def _default(args, ctx):
        return AnalysisSkillResult(
            summary="ok", findings=(), duration_ms=10, errors=(), verdict="passed",
        )
    skill = AnalysisSkill(
        name=name, description=f"test {name}", parameters_schema={},
        run=run or _default, requires_approval=requires_approval,
    )
    registry.register(skill)
    return skill


# ── 编排 + 错误处理 ───────────────────────────────────────────────

def test_run_skill_unknown_returns_skipped(_clean_registry):
    """skill name 不在 registry → verdict=skipped, errors 含 'unknown skill'。"""
    ctx = _make_ctx()
    result = asyncio.run(run_skill("nonexistent", {}, ctx))
    assert result.verdict == "skipped"
    assert any("nonexistent" in e for e in result.errors)


def test_run_skill_invalid_args_returns_skipped():
    """args 不符 parameters_schema → verdict=skipped, errors 含 'invalid args'。"""
    async def _echo(args, ctx):
        return AnalysisSkillResult(summary="x", findings=(), duration_ms=0, errors=(), verdict="passed")
    _register_skill("echo", run=_echo)

    # 注:本期 v1 简化:parameters_schema 走"path" + "timeout"/"top" 几个已知 key
    # 的轻校验;Task 2 只验 path 是否存在 + timeout 范围(top 同),不调 jsonschema。
    # 简化测试:传额外 unknown key → invalid(本期 v1 实现:strict 模式 reject extras)
    ctx = _make_ctx()
    result = asyncio.run(run_skill("echo", {"unknown_key": "x"}, ctx))
    assert result.verdict == "skipped"
    assert any("invalid args" in e for e in result.errors)


def test_run_skill_path_outside_workspace_returns_skipped(tmp_path):
    """path 解析后不在 ctx.workspace 内 → verdict=skipped, errors 含 'outside workspace'。"""
    workspace = tmp_path / "ws"
    workspace.mkdir()
    other = tmp_path / "other"
    other.mkdir()

    async def _needs_path(args, ctx):
        return AnalysisSkillResult(summary="x", findings=(), duration_ms=0, errors=(), verdict="passed")
    _register_skill("p", run=_needs_path)

    ctx = AnalysisSkillContext(workspace=workspace, approval_level="auto", run_id="r1")
    result = asyncio.run(run_skill("p", {"path": str(other)}, ctx))
    assert result.verdict == "skipped"
    assert any("outside workspace" in e for e in result.errors)


def test_run_skill_path_not_found_returns_skipped(tmp_path):
    """path 解析后不存在 → verdict=skipped, errors 含 'path not found'。"""
    workspace = tmp_path / "ws"
    workspace.mkdir()

    async def _p(args, ctx):
        return AnalysisSkillResult(summary="x", findings=(), duration_ms=0, errors=(), verdict="passed")
    _register_skill("p", run=_p)

    ctx = AnalysisSkillContext(workspace=workspace, approval_level="auto", run_id="r1")
    result = asyncio.run(run_skill("p", {"path": "nope.py"}, ctx))
    assert result.verdict == "skipped"
    assert any("path not found" in e for e in result.errors)


# ── timeout ──────────────────────────────────────────────────────

def test_run_skill_timeout_returns_skipped():
    """skill 跑超过 timeout → verdict=skipped, errors 含 'interrupted by timeout'。"""
    async def _slow(args, ctx):
        await asyncio.sleep(5.0)
        return AnalysisSkillResult(summary="x", findings=(), duration_ms=5000, errors=(), verdict="passed")
    _register_skill("slow", run=_slow)

    ctx = _make_ctx()
    start = time.monotonic()
    result = asyncio.run(run_skill("slow", {}, ctx, timeout_s=0.1))
    elapsed = time.monotonic() - start
    assert result.verdict == "skipped"
    assert any("interrupted by timeout" in e for e in result.errors)
    assert elapsed < 1.0   # 0.1s timeout 必须快速返回


# ── 异常聚合 ──────────────────────────────────────────────────────

def test_run_skill_exception_returns_partial():
    """skill 抛异常 → verdict=partial, errors 留 traceback。"""
    async def _boom(args, ctx):
        raise RuntimeError("kapow")
    _register_skill("boom", run=_boom)

    ctx = _make_ctx()
    result = asyncio.run(run_skill("boom", {}, ctx))
    assert result.verdict == "partial"
    assert any("kapow" in e for e in result.errors)


# ── event 投 bus ──────────────────────────────────────────────────

def test_run_skill_emits_start_and_end_events():
    """run 前后各投 1 条 SkillRunStart / SkillRunEnd 到 EventBus(mock)。"""
    bus = MagicMock()
    bus.emit = AsyncMock()

    async def _ok(args, ctx):
        return AnalysisSkillResult(summary="x", findings=(), duration_ms=5, errors=(), verdict="passed")
    _register_skill("ev", run=_ok)

    ctx = _make_ctx()
    asyncio.run(runner.run_skill("ev", {}, ctx, event_bus=bus))

    assert bus.emit.call_count == 2
    start = bus.emit.call_args_list[0].args[0]
    end = bus.emit.call_args_list[1].args[0]
    assert start.kind == "skill_run_start"
    assert start.skill_name == "ev"
    assert end.kind == "skill_run_end"
    assert end.verdict == "passed"
    assert end.finding_count == 0


# ── output trunc(1MB) ─────────────────────────────────────────────

def test_run_skill_truncates_over_1mb_findings():
    """findings > 100 条 → 截到 100 + 1 条 info 提示截断(spec §3)。"""
    big = tuple(
        Finding(severity="info", category="secret", message=f"m{i}")
        for i in range(150)
    )
    async def _many(args, ctx):
        return AnalysisSkillResult(
            summary="x", findings=big, duration_ms=10, errors=(), verdict="failed",
        )
    _register_skill("many", run=_many)

    ctx = _make_ctx()
    result = asyncio.run(run_skill("many", {}, ctx))
    # 100 原始 + 1 截断 info + (总 100 因为 spec 是 trunc 到 100 + 1 info)
    # 实际 spec §3:截到前 100 + 1 info "<N more findings truncated"> = 101
    assert len(result.findings) <= 101
    has_trunc_info = any(
        "truncated" in f.message for f in result.findings if f.severity == "info"
    )
    assert has_trunc_info
