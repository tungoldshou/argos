"""AnalysisSkill frozen dataclass + SkillRegistry 单元测试(spec §2.2 / §2.6)。"""
from __future__ import annotations

import asyncio
from dataclasses import FrozenInstanceError
from typing import Literal

import pytest

from argos_agent.skills_runtime.analysis import (
    AnalysisSkill,
    AnalysisSkillResult,
    AnalysisSkillContext,
    Finding,
)
from argos_agent.skills_runtime.registry import (
    register,
    get,
    list_all,
    _reset_registry,   # 测试用
)


# ── frozen dataclass 测试 ──────────────────────────────────────────

def test_finding_frozen():
    """Finding 是 frozen dataclass;改 severity 抛 FrozenInstanceError。"""
    f = Finding(severity="error", category="secret", message="x")
    with pytest.raises(FrozenInstanceError):
        f.severity = "warning"  # type: ignore[misc]


def test_finding_severity_literal():
    """severity 仅接受 error/warning/info;其他 → ValueError(__post_init__)。"""
    Finding(severity="error", category="x", message="y")
    Finding(severity="warning", category="x", message="y")
    Finding(severity="info", category="x", message="y")
    with pytest.raises(ValueError, match="severity"):
        Finding(severity="critical", category="x", message="y")  # type: ignore[arg-type]


def test_finding_snippet_max_length():
    """snippet 长度 > 120 → ValueError(防 token 暴)。"""
    with pytest.raises(ValueError, match="snippet"):
        Finding(severity="error", category="x", message="y", snippet="a" * 121)


def test_analysis_skill_result_frozen():
    """AnalysisSkillResult 是 frozen;findings 走 tuple(不可变 + 哈希友好)。"""
    r = AnalysisSkillResult(
        summary="x", findings=(), duration_ms=100, errors=(), verdict="passed",
    )
    assert r.findings == ()
    with pytest.raises(FrozenInstanceError):
        r.verdict = "failed"  # type: ignore[misc]


def test_analysis_skill_result_verdict_literal():
    """verdict 仅 5 态(passed/failed/partial/n_a/skipped);其他 → ValueError。"""
    AnalysisSkillResult(summary="x", findings=(), duration_ms=0, errors=(), verdict="passed")
    AnalysisSkillResult(summary="x", findings=(), duration_ms=0, errors=(), verdict="failed")
    AnalysisSkillResult(summary="x", findings=(), duration_ms=0, errors=(), verdict="partial")
    AnalysisSkillResult(summary="x", findings=(), duration_ms=0, errors=(), verdict="n_a")
    AnalysisSkillResult(summary="x", findings=(), duration_ms=0, errors=(), verdict="skipped")
    with pytest.raises(ValueError, match="verdict"):
        AnalysisSkillResult(summary="x", findings=(), duration_ms=0, errors=(), verdict="ok")  # type: ignore[arg-type]


def test_analysis_skill_frozen():
    """AnalysisSkill frozen;name 必含 ASCII 字母数字 + _ + -。"""
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


# ── registry 测试 ──────────────────────────────────────────────────

def test_registry_register_get_identity():
    """register(s) + get(name) → 同一实例(frozen → identity 验);同名重复注册 → ValueError。"""
    _reset_registry()
    async def _r(args, ctx):
        return AnalysisSkillResult(summary="x", findings=(), duration_ms=0, errors=(), verdict="passed")
    s = AnalysisSkill(name="verify", description="x", parameters_schema={}, run=_r, requires_approval=True)
    register(s)
    assert get("verify") is s
    with pytest.raises(ValueError, match="already registered"):
        register(s)


def test_registry_get_unknown_returns_none():
    """get('nonexistent') → None,不抛(spec §3 错误处理表)。"""
    _reset_registry()
    assert get("nonexistent") is None


def test_registry_list_all_empty_after_reset():
    """_reset_registry 后 list_all() → 空。"""
    _reset_registry()
    assert list_all() == []


def test_registry_list_all_preserves_insertion_order():
    """list_all() 按注册顺序返(对位 /skills 列表展示)。"""
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
    """_reset_registry() 清空,用于测试隔离。"""
    async def _r(args, ctx):
        return AnalysisSkillResult(summary="x", findings=(), duration_ms=0, errors=(), verdict="passed")
    register(AnalysisSkill(name="tmp", description="x", parameters_schema={}, run=_r, requires_approval=False))
    assert get("tmp") is not None
    _reset_registry()
    assert get("tmp") is None
