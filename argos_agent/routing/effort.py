"""Effort 等级(契约 §11;spec §8)。

3 档:low / medium / high。显式映射到 LoopConfig 既有字段(max_steps + approval_level),
不引入新 LoopConfig 字段(spec D6)。
"""
from __future__ import annotations

import enum
from dataclasses import dataclass

from argos_agent.approval import ApprovalLevel


class EffortLevel(enum.Enum):
    """任务努力档(契约 §11;spec §8):low=省;AUTO;medium=默认;CONFIRM;high=强;CONFIRM。"""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


@dataclass(frozen=True, slots=True)
class EffortSettings:
    """effort 拆解到 LoopConfig 字段(spec D6:不引入新字段)。"""
    max_steps: int
    approval_level: ApprovalLevel


EFFORT_PRESETS: dict[EffortLevel, EffortSettings] = {
    EffortLevel.LOW: EffortSettings(max_steps=8, approval_level=ApprovalLevel.AUTO),
    EffortLevel.MEDIUM: EffortSettings(max_steps=40, approval_level=ApprovalLevel.CONFIRM),
    EffortLevel.HIGH: EffortSettings(max_steps=80, approval_level=ApprovalLevel.CONFIRM),
}


def effort_settings(level: EffortLevel) -> EffortSettings:
    return EFFORT_PRESETS[level]
