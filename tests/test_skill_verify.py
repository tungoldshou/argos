"""`/verify` 单元测试(spec §2.3 / D9 / D13:用户显式调 Verifier.verify,不绕 propose_verify)。"""
from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from argos_agent.core.verify_gate import Verdict
from argos_agent.skills_runtime.analysis import AnalysisSkillContext
from argos_agent.skills_runtime import registry
from argos_agent.skills_runtime.builtin.verify import run as verify_run


@pytest.fixture(autouse=True)
def _clean():
    registry._reset_registry()
    yield
    registry._reset_registry()


def _ctx(workspace: Path) -> AnalysisSkillContext:
    return AnalysisSkillContext(workspace=workspace, approval_level="auto", run_id="r1")


def test_verify_calls_verifier_verify_directly(tmp_path):
    """`/verify` 走 `Verifier.verify(...)` 入口,不动 `propose_verify`(D9/D13 关键澄清)。"""
    fake_verifier = MagicMock()
    fake_verifier.verify.return_value = Verdict.passed(detail="ok", verify_cmd="pytest -q", attempts=1)

    with patch("argos_agent.skills_runtime.builtin.verify.Verifier", return_value=fake_verifier):
        result = asyncio.run(verify_run({"path": None}, _ctx(tmp_path)))

    assert fake_verifier.verify.called
    assert result.verdict == "passed"


def test_verify_passing_verdict_translates_to_passed(tmp_path):
    """Verifier.passed → AnalysisSkillResult(verdict=passed, findings=())。"""
    fake_verifier = MagicMock()
    fake_verifier.verify.return_value = Verdict.passed(detail="ok", verify_cmd="pytest -q", attempts=1)

    with patch("argos_agent.skills_runtime.builtin.verify.Verifier", return_value=fake_verifier):
        result = asyncio.run(verify_run({"path": None}, _ctx(tmp_path)))

    assert result.verdict == "passed"
    assert result.findings == ()


def test_verify_failing_verdict_translates_to_failed_with_finding(tmp_path):
    """Verifier.failed → verdict=failed, 1 条 error finding。"""
    fake_verifier = MagicMock()
    fake_verifier.verify.return_value = Verdict.failed(
        detail="exit=1, test_bar failed", verify_cmd="pytest -q", attempts=1,
    )

    with patch("argos_agent.skills_runtime.builtin.verify.Verifier", return_value=fake_verifier):
        result = asyncio.run(verify_run({"path": None}, _ctx(tmp_path)))

    assert result.verdict == "failed"
    assert len(result.findings) == 1
    assert result.findings[0].severity == "error"
    assert result.findings[0].category == "verify"


def test_verify_unverifiable_translates_to_partial(tmp_path):
    """Verifier.unverifiable → verdict=partial, errors 透传, findings 空(spec §2.3)。"""
    fake_verifier = MagicMock()
    fake_verifier.verify.return_value = Verdict.unverifiable(
        detail="(无 verify_cmd,未做机检验证)", tampered=[], attempts=1,
    )

    with patch("argos_agent.skills_runtime.builtin.verify.Verifier", return_value=fake_verifier):
        result = asyncio.run(verify_run({"path": None}, _ctx(tmp_path)))

    assert result.verdict == "partial"
    assert result.findings == ()


def test_verify_does_not_call_propose_verify(tmp_path):
    """D9/D13 关键:`/verify` **不**走 `propose_verify` 路径(独立路径不混)。"""
    fake_verifier = MagicMock()
    fake_verifier.verify.return_value = Verdict.passed(detail="ok", verify_cmd="pytest -q", attempts=1)

    with patch("argos_agent.skills_runtime.builtin.verify.Verifier", return_value=fake_verifier):
        with patch("argos_agent.skills_runtime.builtin.verify.propose_verify") as mock_propose:
            asyncio.run(verify_run({"path": None}, _ctx(tmp_path)))
            assert not mock_propose.called


def test_verify_no_verify_cmd_yields_partial_or_na(tmp_path):
    """无 verify_cmd 配置 → verdict=partial / n_a 之一(spec §2.3)。"""
    fake_verifier = MagicMock()
    fake_verifier.verify.return_value = Verdict.unverifiable(
        detail="(无 verify_cmd,未做机检验证)", tampered=[], attempts=1,
    )

    with patch("argos_agent.skills_runtime.builtin.verify.Verifier", return_value=fake_verifier), \
         patch("argos_agent.skills_runtime.builtin.verify._read_verify_cmd", return_value=None):
        result = asyncio.run(verify_run({"path": None}, _ctx(tmp_path)))

    assert result.verdict in ("partial", "n_a")
