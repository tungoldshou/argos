"""Internal documentation."""
from __future__ import annotations

import asyncio
from dataclasses import FrozenInstanceError
from typing import Literal

import pytest

from argos.skills_runtime.analysis import (
    AnalysisSkill,
    AnalysisSkillResult,
    AnalysisSkillContext,
    Finding,
)
from argos.skills_runtime.registry import (
    register,
    get,
    list_all,
    _reset_registry,
)



def test_finding_frozen():
    """Internal documentation."""
    f = Finding(severity="error", category="secret", message="x")
    with pytest.raises(FrozenInstanceError):
        f.severity = "warning"  # type: ignore[misc]


def test_finding_severity_literal():
    """Internal documentation."""
    Finding(severity="error", category="x", message="y")
    Finding(severity="warning", category="x", message="y")
    Finding(severity="info", category="x", message="y")
    with pytest.raises(ValueError, match="severity"):
        Finding(severity="critical", category="x", message="y")  # type: ignore[arg-type]


def test_finding_snippet_max_length():
    """Internal documentation."""
    with pytest.raises(ValueError, match="snippet"):
        Finding(severity="error", category="x", message="y", snippet="a" * 121)


def test_analysis_skill_result_frozen():
    """Internal documentation."""
    r = AnalysisSkillResult(
        summary="x", findings=(), duration_ms=100, errors=(), verdict="passed",
    )
    assert r.findings == ()
    with pytest.raises(FrozenInstanceError):
        r.verdict = "failed"  # type: ignore[misc]


def test_analysis_skill_result_verdict_literal():
    """Internal documentation."""
    AnalysisSkillResult(summary="x", findings=(), duration_ms=0, errors=(), verdict="passed")
    AnalysisSkillResult(summary="x", findings=(), duration_ms=0, errors=(), verdict="failed")
    AnalysisSkillResult(summary="x", findings=(), duration_ms=0, errors=(), verdict="partial")
    AnalysisSkillResult(summary="x", findings=(), duration_ms=0, errors=(), verdict="n_a")
    AnalysisSkillResult(summary="x", findings=(), duration_ms=0, errors=(), verdict="skipped")
    with pytest.raises(ValueError, match="verdict"):
        AnalysisSkillResult(summary="x", findings=(), duration_ms=0, errors=(), verdict="ok")  # type: ignore[arg-type]


def test_analysis_skill_frozen():
    """Internal documentation."""
    async def _noop(args, ctx):
        return AnalysisSkillResult(summary="", findings=(), duration_ms=0, errors=(), verdict="passed")

    s = AnalysisSkill(
        name="verify",
        description="run verify_cmd",
        parameters_schema={"type": "object"},
        run=_noop,
        requires_approval=True,
    )
    assert s.name == "verify"
    assert s.requires_approval is True
    with pytest.raises(FrozenInstanceError):
        s.name = "other"  # type: ignore[misc]
    with pytest.raises(ValueError, match="name"):
        AnalysisSkill(name="bad name", description="x", parameters_schema={}, run=_noop, requires_approval=False)



def test_registry_register_get_identity():
    """Internal documentation."""
    _reset_registry()
    async def _r(args, ctx):
        return AnalysisSkillResult(summary="x", findings=(), duration_ms=0, errors=(), verdict="passed")
    s = AnalysisSkill(name="verify", description="x", parameters_schema={}, run=_r, requires_approval=True)
    register(s)
    assert get("verify") is s
    with pytest.raises(ValueError, match="already registered"):
        register(s)


def test_registry_get_unknown_returns_none():
    """Internal documentation."""
    _reset_registry()
    assert get("nonexistent") is None


def test_registry_list_all_empty_after_reset():
    """Internal documentation."""
    _reset_registry()
    assert list_all() == []


def test_registry_list_all_preserves_insertion_order():
    """Internal documentation."""
    _reset_registry()
    async def _r(args, ctx):
        return AnalysisSkillResult(summary="", findings=(), duration_ms=0, errors=(), verdict="passed")
    for nm in ("verify", "security-review", "simplify"):
        register(AnalysisSkill(
            name=nm, description=f"desc-{nm}", parameters_schema={}, run=_r, requires_approval=False,
        ))
    names = [s.name for s in list_all()]
    assert names == ["verify", "security-review", "simplify"]


def test_registry_clear_for_test():
    """Internal documentation."""
    async def _r(args, ctx):
        return AnalysisSkillResult(summary="x", findings=(), duration_ms=0, errors=(), verdict="passed")
    register(AnalysisSkill(name="tmp", description="x", parameters_schema={}, run=_r, requires_approval=False))
    assert get("tmp") is not None
    _reset_registry()
    assert get("tmp") is None
