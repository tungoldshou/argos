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
