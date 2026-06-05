"""PlanModal 4 选项审批 modal 渲染 + 数字键绑定。"""
from __future__ import annotations

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
