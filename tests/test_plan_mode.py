"""Plan mode 核心数据类 + 异常单元测试。"""
from __future__ import annotations

import pytest

from argos_agent.core.plan_mode import (
    EnterPlanMode,
    ExitPlanMode,
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


# --- EnterPlanMode / ExitPlanMode ---


class _FakeLoop:
    """最小 AgentLoop stub(只暴露 EnterPlanMode/ExitPlanMode 需要的属性)。"""
    def __init__(self, *, busy: bool = False, mode: str = "act"):
        self._busy = busy
        self.mode = mode
        self._plan_decision = None
        self._events = []  # 记录 PhaseChange 事件(若有)

    def _emit_phase(self, phase: str) -> None:
        self._events.append(("phase", phase))


def test_enter_plan_mode_from_act():
    """act → plan 切;emit phase 'plan' 事件;返回 '已切到 plan mode'。"""
    loop = _FakeLoop()
    msg = EnterPlanMode(loop)
    assert loop.mode == "plan"
    assert "plan mode" in msg.lower()
    assert ("phase", "plan") in loop._events


def test_enter_plan_mode_already_in_plan():
    """plan → plan 切提示已在 plan mode。"""
    loop = _FakeLoop(mode="plan")
    msg = EnterPlanMode(loop)
    assert loop.mode == "plan"
    assert "已" in msg or "already" in msg.lower()


def test_enter_plan_mode_when_busy():
    """busy 时 EnterPlanMode 友好提示,不变 mode。"""
    loop = _FakeLoop(busy=True)
    msg = EnterPlanMode(loop)
    assert loop.mode == "act"  # 没变
    assert "esc" in msg.lower() or "打断" in msg or "busy" in msg.lower()


def test_exit_plan_mode_approve_start():
    """plan → act 切;存 decision;返回 '已退出 plan mode,action=approve_start'。"""
    loop = _FakeLoop(mode="plan")
    msg = ExitPlanMode(loop, action="approve_start")
    assert loop.mode == "act"
    assert loop._plan_decision == PlanExitDecision(action="approve_start")
    assert "approve_start" in msg or "退出" in msg


def test_exit_plan_mode_refine_requires_feedback():
    """refine 模式 feedback 为空时报错,不变 mode。"""
    loop = _FakeLoop(mode="plan")
    msg = ExitPlanMode(loop, action="refine", feedback="")
    assert loop.mode == "plan"  # 没变
    assert "feedback" in msg.lower() or "不能为空" in msg or "refine" in msg.lower()
    assert loop._plan_decision is None


def test_exit_plan_mode_refine_with_feedback():
    """refine + 非空 feedback → 切回 act + 存 decision。"""
    loop = _FakeLoop(mode="plan")
    msg = ExitPlanMode(loop, action="refine", feedback="更多上下文")
    assert loop.mode == "act"
    assert loop._plan_decision.feedback == "更多上下文"


def test_exit_plan_mode_not_in_plan():
    """当前不在 plan mode 时 ExitPlanMode 报错。"""
    loop = _FakeLoop(mode="act")
    msg = ExitPlanMode(loop, action="approve_start")
    assert "plan mode" in msg.lower() or "不在" in msg


def test_exit_plan_mode_invalid_action():
    """action 不在 4 选项时报 ValueError(由 PlanExitDecision 抛,被 ExitPlanMode 捕获返错误串)。"""
    loop = _FakeLoop(mode="plan")
    msg = ExitPlanMode(loop, action="bogus")
    assert loop.mode == "plan"  # 没变
    assert "approve_start" in msg or "invalid" in msg.lower() or "approve" in msg


# --- PlanRenderer.render() ---

from argos_agent.core.plan_mode import PlanRenderer  # noqa: E402


def test_render_empty_plan():
    """0 todos + 0 tool_calls 仍产 markdown('无具体任务分解'段)。"""
    md = PlanRenderer.render(goal="noop", todos=[], tool_calls=[])
    assert "# Plan: noop" in md
    assert "无具体任务分解" in md
    assert "审批" in md or "Approve" in md or "approve" in md.lower()


def test_render_with_todos():
    """有 todos 时 markdown 含任务分解列表。"""
    todos = [
        {"step": 1, "description": "Read main.py", "tool": "read_file"},
        {"step": 2, "description": "Edit config", "tool": "edit_file"},
    ]
    md = PlanRenderer.render(goal="fix bug", todos=todos, tool_calls=[])
    assert "Read main.py" in md
    assert "Edit config" in md
    assert "read_file" in md
    assert "edit_file" in md


def test_render_with_tool_calls():
    """有 tool_calls 时 markdown 含工具调用段。"""
    tool_calls = [
        {"tool": "read_file", "args": {"path": "x.py"}},
        {"tool": "run_command", "args": {"command": "pytest"}},
    ]
    md = PlanRenderer.render(goal="refactor", todos=[], tool_calls=tool_calls)
    assert "工具" in md or "tool" in md.lower()
    assert "read_file" in md
    assert "run_command" in md


def test_render_with_risks():
    """有 risks 段时 markdown 含风险段。"""
    md = PlanRenderer.render(
        goal="x", todos=[], tool_calls=[], risks=["rm -rf 风险", "无 verify_cmd"],
    )
    assert "风险" in md
    assert "rm -rf" in md
    assert "verify_cmd" in md


def test_render_goal_truncated_to_title():
    """goal 长时只取前 50 字符作标题(避免 plan 标题过长)。"""
    long_goal = "x" * 200
    md = PlanRenderer.render(goal=long_goal, todos=[], tool_calls=[])
    # 标题行不应含 200 字符
    title_line = [l for l in md.splitlines() if l.startswith("# Plan:")][0]
    assert len(title_line) < 100, f"标题过长: {title_line}"
