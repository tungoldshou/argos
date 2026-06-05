"""Plan mode 核心数据类 + 异常单元测试。"""
from __future__ import annotations

import pytest

from argos_agent.core.plan_mode import (
    PlanExitDecision,
    PlanModeError,
)


def test_plan_mode_error_is_exception():
    """PlanModeError 是 Exception 子类,带 plan mode 错误串。"""
    err = PlanModeError("sandbox tool not allowed in plan mode")
    assert isinstance(err, Exception)
    assert "sandbox" in str(err).lower() or "plan" in str(err).lower()


def test_plan_exit_decision_construction():
    """PlanExitDecision 是 frozen dataclass,4 个 action 互斥。"""
    d1 = PlanExitDecision(action="approve_start")
    d2 = PlanExitDecision(action="approve_accept_edits")
    d3 = PlanExitDecision(action="keep_planning")
    d4 = PlanExitDecision(action="refine", feedback="更多上下文")
    assert d1.action == "approve_start"
    assert d1.feedback is None
    assert d4.feedback == "更多上下文"
    # frozen
    with pytest.raises(Exception):
        d1.action = "other"  # type: ignore[misc]


def test_plan_exit_decision_invalid_action_raises():
    """action 必须是 4 个允许值之一。"""
    with pytest.raises(ValueError):
        PlanExitDecision(action="invalid_action")
