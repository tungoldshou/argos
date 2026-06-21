"""Phase 2:类型基石冻结性 + 字面值与契约 §0 一致。"""
import dataclasses

import pytest

from argos.core import types as T


def test_verdict_status_literal_values():
    # 三态 fail-closed:passed/failed/unverifiable
    assert set(T.VerdictStatus.__args__) == {"passed", "failed", "unverifiable"}


def test_phase_literal_values():
    assert set(T.Phase.__args__) == {"plan", "act", "verify", "report"}


def test_decision_kind_literal_values():
    assert set(T.DecisionKind.__args__) == {"deny", "once", "session", "always"}


def test_risk_level_literal_values():
    assert set(T.RiskLevel.__args__) == {"low", "medium", "high"}


def test_model_tier_name_is_free_string():
    # 已无 worker/premium 档位:profile 名是自由字符串(config.json 里任意命名),不再是 Literal。
    assert T.ModelTierName is str


def test_approval_level_name_values():
    assert set(T.ApprovalLevelName.__args__) == {"observe", "propose", "confirm", "auto"}


# ── CONTRACT A §5:Verdict.no_test + Verdict.no_check() ─────────────────────

def test_verdict_no_test_field_defaults_false():
    """no_test 默认 False,不破坏既有构造点(旧 Verdict.passed/failed/unverifiable 无需传)。"""
    v = T.Verdict(status="passed", detail="ok", verify_cmd="pytest", attempts=1)
    assert v.no_test is False


def test_verdict_no_check_factory():
    """Verdict.no_check() 返 status='unverifiable', no_test=True, tampered=[], verify_cmd=None。"""
    v = T.Verdict.no_check("无 verify_cmd,未做机检验证", attempts=1)
    assert v.status == "unverifiable"
    assert v.no_test is True
    assert v.verify_cmd is None
    assert v.tampered == []
    assert v.attempts == 1


def test_verdict_no_check_is_distinct_from_unverifiable():
    """Verdict.unverifiable 的 no_test 仍是 False(篡改/超时 = 真无法验证,不是无测任务)。"""
    v = T.Verdict.unverifiable("篡改了受保护文件", tampered=["tests/t.py"], attempts=2)
    assert v.status == "unverifiable"
    assert v.no_test is False
    assert "tests/t.py" in v.tampered


def test_verdict_no_check_is_frozen():
    """Verdict 仍是 frozen dataclass,no_test 字段不可原地修改。"""
    v = T.Verdict.no_check("test", attempts=1)
    with pytest.raises((dataclasses.FrozenInstanceError, AttributeError, TypeError)):
        v.no_test = True  # type: ignore[misc]


def test_verdict_no_test_immutability_via_dataclass():
    """frozen=True 保证:no_test 字段存在于 fields 清单。"""
    field_names = {f.name for f in dataclasses.fields(T.Verdict)}
    assert "no_test" in field_names
