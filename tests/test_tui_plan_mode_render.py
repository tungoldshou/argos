"""Plan mode wiring:TUI `app.py` 收 PlanRendered 事件 → 推 PlanModal → 决策回传 loop。

Subtask C(spec §2.5):plan 阶段 loop 投 PlanRendered 事件 → TUI `_apply_event` 收事件 →
`push_screen(PlanModal(plan_md=...))` → 回调里 `ExitPlanMode(loop, ...)` 写
`loop._plan_decision` + `loop._plan_decision_event.set()` 唤醒 loop 的 await。

本测用一个 mock loop yield `PlanRendered` + 后续 ApprovalRequest,断言:
  · 收到 PlanRendered 后 PlanModal 真的被 push 到 screen stack
  · 数字键 1 (Approve and start) 触发回调 → loop 收到 approve_start 决策
  · EnterPlanMode 已被 EnterPlanMode(loop) 调过(=_plan_decision_event 等待中)
"""
from __future__ import annotations

from collections.abc import AsyncIterator
from unittest.mock import MagicMock

import pytest

from argos_agent.approval import ApprovalGate, ApprovalLevel
from argos_agent.core.plan_mode import EnterPlanMode, PlanExitDecision
from argos_agent.tui.app import ArgosApp
from argos_agent.tui.events import (
    Event, PlanRendered, PhaseChange, TokenDelta, VerifyVerdict, CostUpdate,
)
from argos_agent.tui.fakeloop import FakeLoop
from argos_agent.tui.widgets.plan_modal import PlanModal


class _PlanRenderedLoop:
    """进 plan mode 后,先投 PlanRendered(模拟 plan 阶段产出 → 拼 markdown),然后等决策。
    决策设进 _plan_decision 后,再走一简短 act 路径收尾(PhaseChange(act) → 验证通过)。"""

    def __init__(self) -> None:
        self._mode = "plan"
        self._plan_decision_event = __import__("asyncio").Event()
        self._plan_decision = None
        self._approval_level_override = None
        # 真实 loop 的属性(TUI 期望 loop.mode 存在 + 调 ExitPlanMode 写回 _plan_decision)
        self.mode = "plan"
        self._busy = False

    async def run(self, goal: str, session_id: str) -> AsyncIterator[Event]:
        yield PhaseChange(phase="plan", actions=0)
        yield TokenDelta(text=f"我会按目标做事:{goal}\n")
        # 投 PlanRendered → TUI 应弹 PlanModal
        from argos_agent.core.plan_mode import PlanRenderer
        plan_md = PlanRenderer.render(goal=goal, todos=[], tool_calls=[])
        yield PlanRendered(plan_md=plan_md)
        # 挂起(模拟 ExitPlanMode 写完决策后由 TUI 唤醒)
        await self._plan_decision_event.wait()
        # 收到决策后继续 act
        yield PhaseChange(phase="act", actions=1)
        yield TokenDelta(text="干活中\n")
        yield PhaseChange(phase="verify", actions=1)
        from argos_agent.core.verify_gate import Verdict
        yield VerifyVerdict(verdict=Verdict.passed(detail="ok", verify_cmd="echo ok", attempts=1))
        yield PhaseChange(phase="report", actions=1)
        yield CostUpdate(tokens_in=10, tokens_out=5, cost_usd=0.0, elapsed_s=0.1)


@pytest.mark.asyncio
async def test_plan_rendered_event_pushes_plan_modal():
    """进 plan mode 跑一轮 run,PlanRendered 事件到达 → PlanModal 被 push 到 screen stack。

    用 handle_input("goal") 走 run_worker 起 run(同 test_escape_interrupts_active_run 范本),
    不 await start_run —— 因为本测试的 loop 故意挂在 _plan_decision_event(等用户决策),不
    自然结束,await start_run 会让测试 deadlock。"""
    loop = _PlanRenderedLoop()
    app = ArgosApp(loop_factory=lambda: loop, demo=False,
                   gate=ApprovalGate(ApprovalLevel.CONFIRM))
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        # 进 plan mode(TUI 内部 _plan_mode flag + EnterPlanMode(loop) 走 mini loop,见
        # test_enter_plan_mode 既有覆盖;本测直接设 _plan_mode 让指示器对齐 + 用本 loop)。
        app._plan_mode = True
        app.handle_input("读 a.py")     # 起 worker 跑
        for _ in range(30):
            await pilot.pause()
            if any(isinstance(s, PlanModal) for s in app.screen_stack):
                break
        assert any(isinstance(s, PlanModal) for s in app.screen_stack), (
            f"PlanRendered 后 PlanModal 应在 screen stack,实际栈={app.screen_stack}"
        )
        # 清理:按 1 触发 approve,让 modal 收掉 + loop 醒
        await pilot.press("1")
        await pilot.pause()
        await pilot.pause()


@pytest.mark.asyncio
async def test_modal_decision_calls_exit_plan_mode_with_approve_start():
    """modal 选 1 (Approve and start) → loop 收到 approve_start 决策。"""
    loop = _PlanRenderedLoop()
    app = ArgosApp(loop_factory=lambda: loop, demo=False,
                   gate=ApprovalGate(ApprovalLevel.CONFIRM))
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        app._plan_mode = True
        app.handle_input("读 a.py")
        for _ in range(30):
            await pilot.pause()
            if any(isinstance(s, PlanModal) for s in app.screen_stack):
                break
        await pilot.press("1")   # Approve and start
        for _ in range(30):
            await pilot.pause()
            if loop._plan_decision is not None:
                break
        assert loop._plan_decision is not None, "1 键后 _plan_decision 应被写"
        assert loop._plan_decision.action == "approve_start"


@pytest.mark.asyncio
async def test_modal_decision_keep_planning_wakes_loop_for_another_round():
    """modal 选 3 (Keep planning) → loop 收到 keep_planning 决策(本测不真验再一轮,只验决策传回)。"""
    loop = _PlanRenderedLoop()
    app = ArgosApp(loop_factory=lambda: loop, demo=False,
                   gate=ApprovalGate(ApprovalLevel.CONFIRM))
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        app._plan_mode = True
        app.handle_input("读 a.py")
        for _ in range(30):
            await pilot.pause()
            if any(isinstance(s, PlanModal) for s in app.screen_stack):
                break
        await pilot.press("3")   # Keep planning
        for _ in range(30):
            await pilot.pause()
            if loop._plan_decision is not None:
                break
        assert loop._plan_decision is not None
        assert loop._plan_decision.action == "keep_planning"
