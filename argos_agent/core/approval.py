"""审批拨盘类型(契约 §6.3)最小占位 —— Phase 3 canonical 来源(approval.py 主版在包根)。
Phase 3 把旧 approval.py(default-deny + 跨 loop 唤醒)重构进 broker 后,以 Phase 3 为准。
本文件仅供 core 包内部 TYPE_CHECKING import 和 LoopConfig 默认值引用。
"""
from __future__ import annotations

import enum
from dataclasses import dataclass

from argos_agent.core.types import DecisionKind


class ApprovalLevel(enum.Enum):
    OBSERVE = "observe"
    PROPOSE = "propose"
    CONFIRM = "confirm"
    AUTO = "auto"


@dataclass(frozen=True, slots=True)
class Decision:
    kind: DecisionKind
    reason: str = ""

    @property
    def approved(self) -> bool:
        return self.kind != "deny"
