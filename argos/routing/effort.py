from __future__ import annotations

import enum
from dataclasses import dataclass


class EffortLevel(enum.Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


@dataclass(frozen=True, slots=True)
class EffortSettings:
    max_steps: int


EFFORT_PRESETS: dict[EffortLevel, EffortSettings] = {
    EffortLevel.LOW: EffortSettings(max_steps=8),
    EffortLevel.MEDIUM: EffortSettings(max_steps=40),
    EffortLevel.HIGH: EffortSettings(max_steps=80),
}


def effort_settings(level: EffortLevel) -> EffortSettings:
    return EFFORT_PRESETS[level]
