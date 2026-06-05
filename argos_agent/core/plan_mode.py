"""Plan mode 核心(spec §2.1-§2.2)。

包含:
- `PlanModeError`:plan mode 期间调用沙箱工具抛
- `PlanExitDecision`:4 选项审批结果(frozen dataclass)
- (后续 Task 加 EnterPlanMode / ExitPlanMode / PlanRenderer)
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


class PlanModeError(Exception):
    """plan mode 期间调用沙箱工具抛。"""


PlanExitAction = Literal["approve_start", "approve_accept_edits", "keep_planning", "refine"]
_VALID_ACTIONS = ("approve_start", "approve_accept_edits", "keep_planning", "refine")


@dataclass(frozen=True)
class PlanExitDecision:
    """`ExitPlanMode` 工具的 4 选项审批结果。"""
    action: PlanExitAction
    feedback: str | None = None

    def __post_init__(self):
        if self.action not in _VALID_ACTIONS:
            raise ValueError(
                f"PlanExitDecision.action 必须是 {_VALID_ACTIONS} 之一,收到 {self.action!r}"
            )


def EnterPlanMode(loop) -> str:
    """切到 plan-only 模式(等用户审批后 ExitPlanMode 继续)。

    Args:
        loop: AgentLoop 实例(只需 `_busy` / `mode` / `_emit_phase` 3 个属性)

    Returns:
        用户可见消息(成功/错误)
    """
    if getattr(loop, "_busy", False):
        return "错误:当前 run 正在跑,请先 Esc 打断,再 /plan。"
    if getattr(loop, "mode", "act") == "plan":
        return "已在 plan mode。"
    loop.mode = "plan"
    # emit PhaseChange 事件(给前端,标题/边缘光变色)
    if hasattr(loop, "_emit_phase"):
        loop._emit_phase("plan")
    return "已切到 plan mode。"



def ExitPlanMode(loop, action: str, feedback: str | None = None) -> str:
    """退出 plan mode,根据 action 决定下一步。

    Args:
        loop: AgentLoop 实例(只需 `mode` / `_plan_decision` 2 个属性)
        action: 4 选项之一(approve_start / approve_accept_edits / keep_planning / refine)
        feedback: 仅 refine 时用(不能为空)

    Returns:
        用户可见消息
    """
    if getattr(loop, "mode", "act") != "plan":
        return "错误:当前不在 plan mode。"
    if action == "refine" and not (feedback and feedback.strip()):
        return "错误:refine 需要 feedback。"
    try:
        decision = PlanExitDecision(action=action, feedback=feedback)
    except ValueError as e:
        return f"错误:{e}"
    loop.mode = "act"
    loop._plan_decision = decision
    return f"已退出 plan mode,action={action}。"
