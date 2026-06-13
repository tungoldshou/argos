"""verify 分级 + 三态 Verdict fail-closed(契约 §6.1/§6;spec §3.3 L2/§12.5)。"""
import pytest

from argos.core.types import Verdict


def test_verdict_passed_constructor():
    v = Verdict.passed(detail="[exit_code=0]\n12 passed", verify_cmd="pytest -q", attempts=1)
    assert v.status == "passed"
    assert v.verify_cmd == "pytest -q"
    assert v.attempts == 1
    assert v.tampered == []


def test_verdict_failed_constructor():
    v = Verdict.failed(detail="[exit_code=1]\nE assert", verify_cmd="pytest -q", attempts=2)
    assert v.status == "failed"
    assert v.attempts == 2


def test_verdict_unverifiable_constructor():
    v = Verdict.unverifiable(detail="测试被改", tampered=["test_x.py(被修改)"], attempts=1)
    assert v.status == "unverifiable"
    assert v.tampered == ["test_x.py(被修改)"]


def test_verdict_is_frozen():
    v = Verdict.passed(detail="ok", verify_cmd="pytest", attempts=1)
    with pytest.raises((AttributeError, Exception)):
        v.status = "failed"  # type: ignore[misc]


import os
import textwrap
from pathlib import Path

from argos.core.verify_gate import Verifier
from argos import runtime


def _mk_project(tmp_path: Path) -> Path:
    proj = tmp_path / "proj"
    proj.mkdir()
    return proj


@pytest.fixture
def in_project(tmp_path, monkeypatch):
    proj = _mk_project(tmp_path)
    tok = runtime.use_project(str(proj))
    yield proj
    runtime.reset(tok)


def test_verify_none_cmd_returns_unverifiable(in_project):
    # HONESTY CORRECTION:没 verify_cmd → 没有机检命令真的跑过 → 诚实标 "unverifiable",
    # 绝不当 passed(否则违反 HONESTY_SYSTEM 规则 1:未实际运行验证命令不得声称成功)。
    # 无测任务能否完成由 Harness.run_verify_gate 据 "verify_cmd is None" 判定 —— 不 bounce,
    # 但报告诚实标 "未机检验证 (no test command)"。
    v = Verifier(max_rounds=3).verify(None)
    assert v.status == "unverifiable"
    assert v.verify_cmd is None


def test_verify_passing_command(in_project):
    (in_project / "test_ok.py").write_text("def test_ok():\n    assert 1 == 1\n")
    v = Verifier(max_rounds=3).verify("pytest -q test_ok.py")
    assert v.status == "passed"
    assert "[exit_code=0]" in v.detail


def test_verify_failing_command(in_project):
    (in_project / "test_bad.py").write_text("def test_bad():\n    assert 1 == 2\n")
    v = Verifier(max_rounds=3).verify("pytest -q test_bad.py")
    assert v.status == "failed"
    assert "[exit_code=" in v.detail


def test_verify_not_whitelisted_command(in_project):
    v = Verifier(max_rounds=3).verify("rm -rf /")
    assert v.status == "failed"
    assert "白名单" in v.detail


def test_verify_tampering_forces_unverifiable(in_project):
    # 登记受保护测试 → 改它 → 即便命令退出码 0,也判 unverifiable(优先于退出码)。
    test_file = in_project / "test_guard.py"
    test_file.write_text("def test_guard():\n    assert True\n")
    runtime.guard_files(["test_guard.py"])
    test_file.write_text("def test_guard():\n    assert True  # tampered\n")
    v = Verifier(max_rounds=3).verify("pytest -q test_guard.py")
    assert v.status == "unverifiable"
    assert any("test_guard.py" in t for t in v.tampered)


def test_verify_timeout_degrades_to_unverifiable(in_project):
    # 超时 → 无法确认 → 诚实降级 unverifiable(绝不当 passed)。用极短 inline_timeout 触发。
    (in_project / "test_slow.py").write_text(
        "import time\ndef test_slow():\n    time.sleep(2)\n    assert True\n"
    )
    v = Verifier(max_rounds=3, inline_timeout=0.3).verify("pytest -q test_slow.py")
    assert v.status == "unverifiable"
    assert "超时" in v.detail
