"""Internal documentation."""
from __future__ import annotations

import pytest

pytest_plugins = ["tests.e2e.conftest"]


def test_loop_mode_field_defaults_to_act(build_real_loop):
    """Internal documentation."""
    loop = build_real_loop(scripts=["完成。无事可做。"], verify_cmd=None)
    assert hasattr(loop, "mode")
    assert loop.mode == "act"


def test_loop_enter_plan_mode_changes_mode():
    """Internal documentation."""
    from argos.core.plan_mode import EnterPlanMode

    class _StubLoop:
        def __init__(self):
            self._busy = False
            self.mode = "act"
            self.events: list[tuple[str, str]] = []

        def _emit_phase(self, phase: str) -> None:
            self.events.append(("phase", phase))

    loop = _StubLoop()
    msg = EnterPlanMode(loop)  # type: ignore[arg-type]
    assert loop.mode == "plan"
    assert "plan mode" in msg.lower()
    assert ("phase", "plan") in loop.events


def test_loop_enter_then_exit_plan_mode_round_trip():
    """Internal documentation."""
    from argos.core.plan_mode import EnterPlanMode, ExitPlanMode, PlanExitDecision

    class _StubLoop:
        def __init__(self):
            self._busy = False
            self.mode = "act"
            self._plan_decision = None
            self.events: list[tuple[str, str]] = []

        def _emit_phase(self, phase: str) -> None:
            self.events.append(("phase", phase))

    loop = _StubLoop()
    EnterPlanMode(loop)  # type: ignore[arg-type]
    assert loop.mode == "plan"

    msg = ExitPlanMode(loop, action="approve_start")  # type: ignore[arg-type]
    assert loop.mode == "act"
    assert loop._plan_decision == PlanExitDecision(action="approve_start")
    assert "approve_start" in msg or "退出" in msg
    assert ("phase", "plan") in loop.events
