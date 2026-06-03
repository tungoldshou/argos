"""verify 分级 + 三态 Verdict fail-closed(契约 §6.1/§6;spec §3.3 L2/§12.5)。"""
import pytest

from argos_agent.core.types import Verdict


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
