from __future__ import annotations

import enum
from dataclasses import dataclass

from argos.approval import ApprovalLevel


class EffortLevel(enum.Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


@dataclass(frozen=True, slots=True)
class EffortSettings:
    max_steps: int
    approval_level: ApprovalLevel


EFFORT_PRESETS: dict[EffortLevel, EffortSettings] = {
    EffortLevel.LOW: EffortSettings(max_steps=8, approval_level=ApprovalLevel.AUTO),
    EffortLevel.MEDIUM: EffortSettings(max_steps=40, approval_level=ApprovalLevel.CONFIRM),
    EffortLevel.HIGH: EffortSettings(max_steps=80, approval_level=ApprovalLevel.CONFIRM),
}


def effort_settings(level: EffortLevel) -> EffortSettings:
    return EFFORT_PRESETS[level]
