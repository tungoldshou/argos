from __future__ import annotations

import pytest

from argos.core.plan_mode import (
    EnterPlanMode,
    ExitPlanMode,
    PlanExitDecision,
    PlanModeError,
    is_plan_mode,
    set_plan_mode,
)


def test_plan_mode_error_is_exception():
    err = PlanModeError("sandbox tool not allowed in plan mode")
    assert isinstance(err, Exception)
    assert "sandbox" in str(err).lower() or "plan" in str(err).lower()


def test_plan_exit_decision_construction():
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
    with pytest.raises(ValueError):
        PlanExitDecision(action="invalid_action")


# --- EnterPlanMode / ExitPlanMode ---


class _FakeLoop:
    def __init__(self, *, busy: bool = False, mode: str = "act"):
        self._busy = busy
        self.mode = mode
        self._plan_decision = None
        self._events = []

    def _emit_phase(self, phase: str) -> None:
        self._events.append(("phase", phase))


def test_enter_plan_mode_from_act():
    loop = _FakeLoop()
    msg = EnterPlanMode(loop)
    assert loop.mode == "plan"
    assert "plan mode" in msg.lower()
    assert ("phase", "plan") in loop._events


def test_enter_plan_mode_already_in_plan():
    loop = _FakeLoop(mode="plan")
    msg = EnterPlanMode(loop)
    assert loop.mode == "plan"
    assert "已" in msg or "already" in msg.lower()


def test_enter_plan_mode_when_busy():
    loop = _FakeLoop(busy=True)
    msg = EnterPlanMode(loop)
    assert loop.mode == "act"
    assert "esc" in msg.lower() or "打断" in msg or "busy" in msg.lower()


def test_exit_plan_mode_approve_start():
    loop = _FakeLoop(mode="plan")
    msg = ExitPlanMode(loop, action="approve_start")
    assert loop.mode == "act"
    assert loop._plan_decision == PlanExitDecision(action="approve_start")
    assert "approve_start" in msg or "退出" in msg


def test_exit_plan_mode_refine_requires_feedback():
    import asyncio
    loop = _FakeLoop(mode="plan")
    loop._plan_decision_event = asyncio.Event()
    msg = ExitPlanMode(loop, action="refine", feedback="")
    assert loop.mode == "plan"
    assert "feedback" in msg.lower() or "不能为空" in msg or "refine" in msg.lower()
    assert loop._plan_decision is None
    assert not loop._plan_decision_event.is_set(), (
        "ExitPlanMode 在校验失败时不应唤醒 loop,否则 Refine 会被静默兜底成 Approve"
    )


def test_exit_plan_mode_succeeds_sets_event():
    import asyncio
    loop = _FakeLoop(mode="plan")
    loop._plan_decision_event = asyncio.Event()
    msg = ExitPlanMode(loop, action="approve_start")
    assert loop.mode == "act"
    assert loop._plan_decision == PlanExitDecision(action="approve_start")
    assert loop._plan_decision_event.is_set(), (
        "ExitPlanMode 成功后应唤醒 loop 的 await event,而不是让 caller 手动 set"
    )


def test_exit_plan_mode_refine_with_feedback_sets_event():
    import asyncio
    loop = _FakeLoop(mode="plan")
    loop._plan_decision_event = asyncio.Event()
    msg = ExitPlanMode(loop, action="refine", feedback="更多上下文")
    assert loop.mode == "act"
    assert loop._plan_decision.feedback == "更多上下文"
    assert loop._plan_decision_event.is_set()


def test_exit_plan_mode_refine_with_feedback():
    loop = _FakeLoop(mode="plan")
    msg = ExitPlanMode(loop, action="refine", feedback="更多上下文")
    assert loop.mode == "act"
    assert loop._plan_decision.feedback == "更多上下文"


def test_exit_plan_mode_not_in_plan():
    loop = _FakeLoop(mode="act")
    msg = ExitPlanMode(loop, action="approve_start")
    assert "plan mode" in msg.lower() or "不在" in msg


def test_exit_plan_mode_invalid_action():
    loop = _FakeLoop(mode="plan")
    msg = ExitPlanMode(loop, action="bogus")
    assert loop.mode == "plan"
    assert "approve_start" in msg or "invalid" in msg.lower() or "approve" in msg


# --- PlanRenderer.render() ---

from argos.core.plan_mode import PlanRenderer  # noqa: E402


def test_render_empty_plan():
    md = PlanRenderer.render(goal="noop", todos=[], tool_calls=[])
    assert "# Plan: noop" in md
    assert "无具体任务分解" in md or "no specific task breakdown" in md.lower()
    assert "审批" in md or "Approve" in md or "approve" in md.lower()


def test_render_with_todos():
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
    tool_calls = [
        {"tool": "read_file", "args": {"path": "x.py"}},
        {"tool": "run_command", "args": {"command": "pytest"}},
    ]
    md = PlanRenderer.render(goal="refactor", todos=[], tool_calls=tool_calls)
    assert "工具" in md or "tool" in md.lower()
    assert "read_file" in md
    assert "run_command" in md


def test_render_with_risks():
    md = PlanRenderer.render(
        goal="x", todos=[], tool_calls=[], risks=["rm -rf 风险", "无 verify_cmd"],
    )
    assert "风险" in md or "risk" in md.lower()
    assert "rm -rf" in md
    assert "verify_cmd" in md


def test_render_goal_truncated_to_title():
    long_goal = "x" * 200
    md = PlanRenderer.render(goal=long_goal, todos=[], tool_calls=[])
    title_line = [l for l in md.splitlines() if l.startswith("# Plan:")][0]
    assert len(title_line) < 100, f"标题过长: {title_line}"




def test_set_and_get_plan_mode():
    set_plan_mode(True)
    try:
        assert is_plan_mode() is True
    finally:
        set_plan_mode(False)
    assert is_plan_mode() is False


def test_sandbox_tool_blocked_in_plan_mode():
    from argos.tools import run_command_gated
    set_plan_mode(True)
    try:
        result = run_command_gated(command="echo hello")
        assert "plan" in result.lower() or "错误" in result
    finally:
        set_plan_mode(False)


def test_write_file_blocked_in_plan_mode():
    from argos.tools import write_file_gated
    set_plan_mode(True)
    try:
        result = write_file_gated(path="x.py", content="y")
        assert "plan" in result.lower() or "错误" in result
    finally:
        set_plan_mode(False)


def test_edit_file_blocked_in_plan_mode():
    from argos.tools import edit_file_gated
    set_plan_mode(True)
    try:
        result = edit_file_gated(path="x.py", old="a", new="b")
        assert "plan" in result.lower() or "错误" in result
    finally:
        set_plan_mode(False)


def test_sandbox_tools_work_in_normal_act_mode():
    from argos.tools import run_command_gated
    set_plan_mode(False)
    result = run_command_gated(command="echo hello")
    assert "plan mode" not in result.lower()


def test_enter_plan_mode_sets_module_state():
    from argos.core.plan_mode import EnterPlanMode

    class _Loop:
        mode = "act"
        _busy = False
        def _emit_phase(self, p): pass

    set_plan_mode(False)
    try:
        EnterPlanMode(_Loop())  # type: ignore[arg-type]
        assert is_plan_mode() is True
    finally:
        set_plan_mode(False)


def test_exit_plan_mode_clears_module_state():
    from argos.core.plan_mode import EnterPlanMode, ExitPlanMode

    class _Loop:
        mode = "act"
        _busy = False
        def _emit_phase(self, p): pass

    set_plan_mode(False)
    try:
        EnterPlanMode(_Loop())  # type: ignore[arg-type]
        assert is_plan_mode() is True
        loop2 = _Loop()
        loop2.mode = "plan"
        ExitPlanMode(loop2, action="approve_start")  # type: ignore[arg-type]
        assert is_plan_mode() is False
    finally:
        set_plan_mode(False)
