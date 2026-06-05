"""PlanModal 4 选项审批 modal 渲染 + 数字键绑定。"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from argos_agent.tui.widgets.plan_modal import PlanModal, PlanDecision


def test_plan_modal_4_options():
    """PlanModal 暴露 4 选项 actions。"""
    m = PlanModal(plan_md="# Plan: ...\n...审批段...")
    assert m.options == ["approve_start", "approve_accept_edits", "keep_planning", "refine"]


def test_plan_decision_construction():
    """PlanDecision 是 frozen dataclass。"""
    d = PlanDecision(action="approve_start")
    assert d.action == "approve_start"
    assert d.feedback is None
    with pytest.raises(Exception):
        d.action = "other"  # type: ignore[misc]


def test_plan_decision_refine_has_feedback():
    d = PlanDecision(action="refine", feedback="补充上下文")
    assert d.feedback == "补充上下文"


def test_plan_modal_stores_plan_md():
    """PlanModal 构造时存 plan_md,后续可在 compose 用。"""
    md = "# Plan\n## 任务分解\n- [ ] step 1\n## 审批\n..."
    m = PlanModal(plan_md=md)
    assert m.plan_md == md


@pytest.mark.parametrize(
    ("btn_id", "expected_action", "expected_feedback"),
    [
        ("btn-1", "approve_start", None),
        ("btn-2", "approve_accept_edits", None),
        ("btn-3", "keep_planning", None),
        ("btn-4", "refine", ""),  # refine 经 action_decide 返空 feedback,跟数字键 4 一致
    ],
)
def test_plan_modal_button_routes_through_action_decide(
    btn_id, expected_action, expected_feedback
):
    """按钮点击路径必须与数字键路径走 action_decide,产出相同 PlanDecision。"""
    m = PlanModal(plan_md="x")
    m.dismiss = AsyncMock()

    event = MagicMock()
    event.button.id = btn_id

    m.on_button_pressed(event)

    m.dismiss.assert_called_once_with(
        PlanDecision(action=expected_action, feedback=expected_feedback)
    )
