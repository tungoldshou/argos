"""Internal documentation."""
from __future__ import annotations

import os
import textwrap
from pathlib import Path

import pytest

from argos import runtime
from argos.core.types import Verdict
from argos.core.verify_gate import Verifier
from argos.verify.self_test import TestGenerator, TestProposal, _is_whitelisted




@pytest.fixture
def in_tmp_workspace(tmp_path, monkeypatch):
    """Internal documentation."""
    monkeypatch.setenv("ARGOS_NO_MEMORY", "1")
    token = runtime.use_project(str(tmp_path))
    yield tmp_path
    runtime.reset(token)


def _make_proposer_with(cmd: str, content: str, test_path: str = "test_argos_selftest.py"):
    """Internal documentation."""
    def _prop(goal: str, workspace: Path):
        return (cmd, content, test_path)
    return _prop




def test_self_test_passes_when_canary_and_real_both_pass(
    in_tmp_workspace, monkeypatch,
):
    """Internal documentation."""
    monkeypatch.setenv("ARGOS_SELF_TEST", "1")
    ws = in_tmp_workspace
    (ws / "sentinel.py").write_text("ANSWER = 42\n")

    test_content = textwrap.dedent("""
        import sys, importlib.util
        from pathlib import Path
        # The import must depend on sentinel.py inside the test workspace.
        spec = importlib.util.spec_from_file_location("sentinel", Path("sentinel.py").resolve())
        mod = importlib.util.module_from_spec(spec)  # type: ignore
        spec.loader.exec_module(mod)  # type: ignore
        assert mod.ANSWER == 42
    """).strip()
    proposer = _make_proposer_with("python3 test_argos_selftest.py", test_content)
    gen = TestGenerator(proposer=proposer)
    v = Verifier(test_generator=gen, goal="check sentinel.ANSWER == 42")
    verdict = v.verify(verify_cmd=None, attempts=1)

    assert verdict.status == "passed", verdict
    assert verdict.self_verified is True, f"自验证应标 self_verified=True,实得 {verdict!r}"
    assert "[self_verified]" in verdict.detail
    assert verdict.verify_cmd is not None
    assert "test_argos_selftest.py" in verdict.verify_cmd




def test_self_test_discards_noop_test_via_canary(
    in_tmp_workspace, monkeypatch,
):
    """Internal documentation."""
    monkeypatch.setenv("ARGOS_SELF_TEST", "1")
    test_content = "# will be discarded by canary\n"
    proposer = _make_proposer_with(_trivially_passing_echo_cmd(), test_content)
    gen = TestGenerator(proposer=proposer)
    v = Verifier(test_generator=gen, goal="...")
    verdict = v.verify(verify_cmd=None, attempts=1)

    assert verdict.status == "unverifiable", f"废测试应被丢弃回退 unverifiable,实得 {verdict!r}"
    assert verdict.self_verified is False
    assert "无 verify_cmd" in verdict.detail


def test_self_test_no_proposer_no_self_test(
    in_tmp_workspace, monkeypatch,
):
    """Internal documentation."""
    monkeypatch.setenv("ARGOS_SELF_TEST", "1")
    gen = TestGenerator(proposer=None)
    v = Verifier(test_generator=gen, goal="...")
    verdict = v.verify(verify_cmd=None, attempts=1)
    assert verdict.status == "unverifiable"


def _trivially_passing_py_cmd() -> str:
    """Internal documentation."""
    return 'python3 -c "import sys; sys.exit(0)"'


def _trivially_passing_echo_cmd() -> str:
    """Internal documentation."""
    return "echo argos_selftest"




def test_self_verified_verdict_distinguishable_from_user_verified(
    in_tmp_workspace, monkeypatch,
):
    """Internal documentation."""
    # user-level passed(self_verified=False)
    user_v = Verdict.passed(
        detail="[exit_code=0]", verify_cmd="pytest -q", attempts=1,
    )
    assert user_v.self_verified is False

    # self-level passed(self_verified=True)
    self_v = Verdict.passed_self(
        detail="[self_verified] auto", verify_cmd="pytest -q", attempts=1,
    )
    assert self_v.status == "passed"
    assert self_v.self_verified is True

    assert (user_v.status == "passed" and user_v.self_verified is False)
    assert (self_v.status == "passed" and self_v.self_verified is True)
    assert (user_v.status, user_v.self_verified) != (self_v.status, self_v.self_verified)


def test_self_verified_passed_carries_self_verified_marker_in_detail(
    in_tmp_workspace, monkeypatch,
):
    """Internal documentation."""
    monkeypatch.setenv("ARGOS_SELF_TEST", "1")
    ws = in_tmp_workspace
    (ws / "thing.py").write_text("X = 1\n")
    test_content = textwrap.dedent("""
        import importlib.util
        from pathlib import Path
        spec = importlib.util.spec_from_file_location("thing", Path("thing.py").resolve())
        m = importlib.util.module_from_spec(spec)  # type: ignore
        spec.loader.exec_module(m)  # type: ignore
        assert m.X == 1
    """).strip()
    proposer = _make_proposer_with("python3 test_argos_selftest.py", test_content)
    gen = TestGenerator(proposer=proposer)
    v = Verifier(test_generator=gen, goal="verify X==1")
    verdict = v.verify(verify_cmd=None, attempts=1)
    assert verdict.status == "passed"
    assert verdict.self_verified is True
    assert "[self_verified]" in verdict.detail
    assert "较弱" in verdict.detail or "reviewer" in verdict.detail.lower()




def test_self_test_default_off_returns_unverifiable(in_tmp_workspace, monkeypatch):
    """Internal documentation."""
    monkeypatch.delenv("ARGOS_SELF_TEST", raising=False)

    proposer_called = {"n": 0}
    def _spy(goal, workspace):
        proposer_called["n"] += 1
        return ("true", "# never should run", "t.py")
    gen = TestGenerator(proposer=_spy)
    v = Verifier(test_generator=gen, goal="x")
    verdict = v.verify(verify_cmd=None, attempts=1)
    assert verdict.status == "unverifiable"
    assert verdict.self_verified is False
    assert proposer_called["n"] == 0, "flag off 时 proposer 不应被调"


def test_self_test_flag_off_keeps_existing_behavior(in_tmp_workspace, monkeypatch):
    """Internal documentation."""
    monkeypatch.delenv("ARGOS_SELF_TEST", raising=False)
    (in_tmp_workspace / "thing.py").write_text("X = 1\n")
    v = Verifier()
    verdict = v.verify(verify_cmd=_trivially_passing_py_cmd(), attempts=1)
    assert verdict.status == "passed"
    assert verdict.self_verified is False   # user-level




def test_self_test_rejects_cmd_not_in_whitelist(in_tmp_workspace, monkeypatch):
    """Internal documentation."""
    monkeypatch.setenv("ARGOS_SELF_TEST", "1")
    proposer = _make_proposer_with("rm -rf /tmp/nonexistent_argos_dir", "# x")
    gen = TestGenerator(proposer=proposer)
    v = Verifier(test_generator=gen, goal="x")
    verdict = v.verify(verify_cmd=None, attempts=1)
    assert verdict.status == "unverifiable"
    assert verdict.self_verified is False




def test_test_generator_canary_check_unit(tmp_path):
    """Internal documentation."""
    gen = TestGenerator(
        proposer=_make_proposer_with("echo trivially-passing", "# x"),
    )
    proposal = gen.propose_and_validate(goal="x", workspace=tmp_path)
    assert proposal is None


def test_test_generator_writes_test_file_and_canary_passes(tmp_path, monkeypatch):
    """Internal documentation."""
    from argos import runtime
    token = runtime.use_project(str(tmp_path))
    try:
        (tmp_path / "lib.py").write_text("ANS = 7\n")
        test_content = textwrap.dedent("""
            import importlib.util
            from pathlib import Path
            s = importlib.util.spec_from_file_location("lib", Path("lib.py").resolve())
            m = importlib.util.module_from_spec(s)  # type: ignore
            s.loader.exec_module(m)  # type: ignore
            assert m.ANS == 7
        """).strip()
        gen = TestGenerator(
            proposer=_make_proposer_with(
                "python3 test_argos_selftest.py", test_content,
            ),
        )
        proposal = gen.propose_and_validate(goal="x", workspace=tmp_path)
        assert proposal is not None
        assert proposal.canary_passed is True
        assert (tmp_path / "test_argos_selftest.py").exists()
        assert "python3" in proposal.cmd
    finally:
        runtime.reset(token)


def test_is_whitelisted():
    """Internal documentation."""
    assert _is_whitelisted("pytest -q") is True
    assert _is_whitelisted("python3 -c 'x'") is True
    assert _is_whitelisted("python3 -c 'exit 0'") is True
    assert _is_whitelisted("echo x") is True
    assert _is_whitelisted("rm -rf /tmp") is False
    assert _is_whitelisted("curl http://x") is False
    assert _is_whitelisted("bash -c 'echo x'") is False
    assert _is_whitelisted("true") is False
    assert _is_whitelisted("") is False
