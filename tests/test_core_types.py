"""Phase 2:类型基石冻结性 + 字面值与契约 §0 一致。"""
import dataclasses

import pytest

from argos_agent.core import types as T


def test_verdict_status_literal_values():
    # 三态 fail-closed:passed/failed/unverifiable
    assert set(T.VerdictStatus.__args__) == {"passed", "failed", "unverifiable"}


def test_phase_literal_values():
    assert set(T.Phase.__args__) == {"plan", "act", "verify", "report"}


def test_decision_kind_literal_values():
    assert set(T.DecisionKind.__args__) == {"deny", "once", "session", "always"}


def test_risk_level_literal_values():
    assert set(T.RiskLevel.__args__) == {"low", "medium", "high"}


def test_model_tier_literal_values():
    assert set(T.ModelTierName.__args__) == {"worker", "premium"}


def test_approval_level_name_values():
    assert set(T.ApprovalLevelName.__args__) == {"observe", "propose", "confirm", "auto"}
