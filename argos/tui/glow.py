"""Internal documentation."""
from __future__ import annotations

from textual.color import Color

IDLE_BORDER = Color(46, 49, 66)
SUCCESS = Color(158, 206, 106)         # $success
WARNING = Color(224, 175, 104)
ERROR = Color(247, 118, 142)           # $error

_PHASE = {
    "plan": Color(122, 162, 247),
    "act": Color(224, 175, 104),
    "verify": Color(115, 218, 202),
    "report": Color(169, 177, 214),
}


def phase_color(phase: str) -> Color:
    return _PHASE.get(phase, IDLE_BORDER)


def verdict_color(status: str) -> Color:
    return {"passed": SUCCESS, "failed": ERROR, "unverifiable": WARNING}.get(status, IDLE_BORDER)


def verdict_color_self_aware(status: str, self_verified: bool = False) -> Color:
    """Internal documentation."""
    if status == "passed" and self_verified:
        return WARNING
    return verdict_color(status)


def verdict_border_color(verdict) -> Color:
    """Internal documentation."""
    if getattr(verdict, "no_test", False):
        return IDLE_BORDER
    return verdict_color_self_aware(verdict.status, getattr(verdict, "self_verified", False))


def breathe(color: Color, t: float) -> Color:
    """Internal documentation."""
    import math

    k = 0.55 + 0.45 * (0.5 - 0.5 * math.cos(2 * math.pi * t))  # 0.55↔1.0
    return Color(int(color.r * k), int(color.g * k), int(color.b * k))
