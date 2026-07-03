"""Internal documentation."""
from __future__ import annotations

import asyncio
import time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from argos.skills_runtime.analysis import (
    AnalysisSkill,
    AnalysisSkillContext,
    AnalysisSkillResult,
    Finding,
)
from argos.skills_runtime import registry, runner
from argos.skills_runtime.runner import run_skill


@pytest.fixture(autouse=True)
def _clean_registry():
    """Internal documentation."""
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
    """Internal documentation."""
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



def test_run_skill_unknown_returns_skipped(_clean_registry):
    """Internal documentation."""
    ctx = _make_ctx()
    result = asyncio.run(run_skill("nonexistent", {}, ctx))
    assert result.verdict == "skipped"
    assert any("nonexistent" in e for e in result.errors)


def test_run_skill_invalid_args_returns_skipped():
    """Internal documentation."""
    async def _echo(args, ctx):
        return AnalysisSkillResult(summary="x", findings=(), duration_ms=0, errors=(), verdict="passed")
    _register_skill("echo", run=_echo)

    ctx = _make_ctx()
    result = asyncio.run(run_skill("echo", {"unknown_key": "x"}, ctx))
    assert result.verdict == "skipped"
    assert any("invalid args" in e for e in result.errors)


def test_run_skill_path_outside_workspace_returns_skipped(tmp_path):
    """Internal documentation."""
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
    """Internal documentation."""
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
    """Internal documentation."""
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
    assert elapsed < 1.0



def test_run_skill_exception_returns_partial():
    """Internal documentation."""
    async def _boom(args, ctx):
        raise RuntimeError("kapow")
    _register_skill("boom", run=_boom)

    ctx = _make_ctx()
    result = asyncio.run(run_skill("boom", {}, ctx))
    assert result.verdict == "partial"
    assert any("kapow" in e for e in result.errors)



def test_run_skill_emits_start_and_end_events():
    """Internal documentation."""
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
    """Internal documentation."""
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
    assert len(result.findings) <= 101
    has_trunc_info = any(
        "truncated" in f.message for f in result.findings if f.severity == "info"
    )
    assert has_trunc_info
