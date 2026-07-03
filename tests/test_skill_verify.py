"""Internal documentation."""
from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from argos.core.verify_gate import Verdict
from argos.skills_runtime.analysis import AnalysisSkillContext
from argos.skills_runtime import registry
from argos.skills_runtime.builtin.verify import run as verify_run


@pytest.fixture(autouse=True)
def _clean():
    registry._reset_registry()
    yield
    registry._reset_registry()


def _ctx(workspace: Path) -> AnalysisSkillContext:
    return AnalysisSkillContext(workspace=workspace, approval_level="auto", run_id="r1")


def test_read_verify_cmd_honors_argos_config_dir(tmp_path, monkeypatch):
    """`/verify` default command must come from the active Argos config dir."""
    from argos.skills_runtime.builtin.verify import _read_verify_cmd

    cfg_dir = tmp_path / ".argos"
    cfg_dir.mkdir()
    monkeypatch.setenv("ARGOS_CONFIG_DIR", str(cfg_dir))
    (cfg_dir / "config.json").write_text('{"verify_cmd": "echo from-config-dir"}', encoding="utf-8")

    assert _read_verify_cmd() == "echo from-config-dir"


def test_verify_calls_verifier_verify_directly(tmp_path):
    """Internal documentation."""
    fake_verifier = MagicMock()
    fake_verifier.verify.return_value = Verdict.passed(detail="ok", verify_cmd="pytest -q", attempts=1)

    with patch("argos.skills_runtime.builtin.verify.Verifier", return_value=fake_verifier):
        result = asyncio.run(verify_run({"path": None}, _ctx(tmp_path)))

    assert fake_verifier.verify.called
    assert result.verdict == "passed"


def test_verify_passing_verdict_translates_to_passed(tmp_path):
    """Verifier.passed → AnalysisSkillResult(verdict=passed, findings=())。"""
    fake_verifier = MagicMock()
    fake_verifier.verify.return_value = Verdict.passed(detail="ok", verify_cmd="pytest -q", attempts=1)

    with patch("argos.skills_runtime.builtin.verify.Verifier", return_value=fake_verifier):
        result = asyncio.run(verify_run({"path": None}, _ctx(tmp_path)))

    assert result.verdict == "passed"
    assert result.findings == ()


def test_verify_failing_verdict_translates_to_failed_with_finding(tmp_path):
    """Internal documentation."""
    fake_verifier = MagicMock()
    fake_verifier.verify.return_value = Verdict.failed(
        detail="exit=1, test_bar failed", verify_cmd="pytest -q", attempts=1,
    )

    with patch("argos.skills_runtime.builtin.verify.Verifier", return_value=fake_verifier):
        result = asyncio.run(verify_run({"path": None}, _ctx(tmp_path)))

    assert result.verdict == "failed"
    assert len(result.findings) == 1
    assert result.findings[0].severity == "error"
    assert result.findings[0].category == "verify"


def test_verify_unverifiable_translates_to_partial(tmp_path):
    """Internal documentation."""
    fake_verifier = MagicMock()
    fake_verifier.verify.return_value = Verdict.unverifiable(
        detail="(无 verify_cmd,未做机检验证)", tampered=[], attempts=1,
    )

    with patch("argos.skills_runtime.builtin.verify.Verifier", return_value=fake_verifier):
        result = asyncio.run(verify_run({"path": None}, _ctx(tmp_path)))

    assert result.verdict == "partial"
    assert result.findings == ()


def test_verify_does_not_call_propose_verify(tmp_path):
    """Internal documentation."""
    fake_verifier = MagicMock()
    fake_verifier.verify.return_value = Verdict.passed(detail="ok", verify_cmd="pytest -q", attempts=1)

    with patch("argos.skills_runtime.builtin.verify.Verifier", return_value=fake_verifier):
        with patch("argos.skills_runtime.builtin.verify.propose_verify") as mock_propose:
            asyncio.run(verify_run({"path": None}, _ctx(tmp_path)))
            assert not mock_propose.called


def test_verify_no_verify_cmd_yields_partial_or_na(tmp_path):
    """Internal documentation."""
    fake_verifier = MagicMock()
    fake_verifier.verify.return_value = Verdict.unverifiable(
        detail="(无 verify_cmd,未做机检验证)", tampered=[], attempts=1,
    )

    with patch("argos.skills_runtime.builtin.verify.Verifier", return_value=fake_verifier),\
         patch("argos.skills_runtime.builtin.verify._read_verify_cmd", return_value=None):
        result = asyncio.run(verify_run({"path": None}, _ctx(tmp_path)))

    assert result.verdict in ("partial", "n_a")
