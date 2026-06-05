"""AgentLoop.mode 字段 + EnterPlanMode/ExitPlanMode 集成测试。

铁证(Task 5, plan docs/superpowers/plans/2026-06-05-plan-mode.md):
  · AgentLoop.__init__ 设 `self.mode: str = "act"`,真栈真 loop 也成立;
  · EnterPlanMode(loop) 把 mode 切到 "plan";
  · EnterPlanMode → ExitPlanMode 往返把 mode 切回 "act" 并存 decision。

夹具来源:tests/e2e/conftest.py (build_real_loop / store / in_project)。
本文件在 tests/ 根,需显式 pytest_plugins 拉 e2e conftest 的 fixtures。
"""
from __future__ import annotations

import pytest

# 拉 tests/e2e/conftest.py 里的 build_real_loop / store / in_project fixtures(同 test_loop_snapshot.py)。
pytest_plugins = ["tests.e2e.conftest"]


def test_loop_mode_field_defaults_to_act(build_real_loop):
    """AgentLoop 默认 mode = 'act'(真栈 + ScriptedModelClient 装配,字段真的存在)。"""
    # 不需要真跑 run() —— 只验 init 后 loop.mode 字段存在且默认为 "act"。
    # ScriptedModelClient 至少要 1 条 script 才能 init(否则抛 ValueError)—— 给个最便宜的
    # "直接完成" 脚本,但此测试不 drain,只构造 loop 看字段。
    loop = build_real_loop(scripts=["完成。无事可做。"], verify_cmd=None)
    assert hasattr(loop, "mode")
    assert loop.mode == "act"


def test_loop_enter_plan_mode_changes_mode():
    """EnterPlanMode(loop) 把 stub loop 的 mode 切到 'plan'(最小回归保护)。"""
    from argos_agent.core.plan_mode import EnterPlanMode

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
    # _emit_phase 应被调用("plan"),给前端 PhaseChange 事件用。
    assert ("phase", "plan") in loop.events


def test_loop_enter_then_exit_plan_mode_round_trip():
    """EnterPlanMode → ExitPlanMode 往返:mode 回 'act' + _plan_decision 存住用户决策。"""
    from argos_agent.core.plan_mode import EnterPlanMode, ExitPlanMode, PlanExitDecision

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
    # 两次 phase emit:plan → act(前端据此切回主色调)
    assert ("phase", "plan") in loop.events
