"""工作态阶段映射边缘光(spec §工作态边缘光)。颜色=真实 phase/verdict,非随机彩虹。"""
from __future__ import annotations

from textual.color import Color

IDLE_BORDER = Color(60, 60, 70)        # #3c3c46 中性灰(idle 灭)
SUCCESS = Color(158, 206, 106)         # $success
WARNING = Color(224, 175, 104)         # $warning 暖橙
ERROR = Color(247, 118, 142)           # $error

_PHASE = {
    "plan": Color(122, 162, 247),      # 冷靛蓝
    "act": Color(224, 175, 104),       # 暖橙(主强调,动手是主戏)
    "verify": Color(115, 218, 202),    # 冷青
    "report": Color(169, 177, 214),    # 暖灰
}


def phase_color(phase: str) -> Color:
    return _PHASE.get(phase, IDLE_BORDER)


def verdict_color(status: str) -> Color:
    return {"passed": SUCCESS, "failed": ERROR, "unverifiable": WARNING}.get(status, IDLE_BORDER)


def breathe(color: Color, t: float) -> Color:
    """t∈[0,1] 正弦相位 → 在 color 与略暗之间插值(呼吸)。"""
    import math

    k = 0.55 + 0.45 * (0.5 - 0.5 * math.cos(2 * math.pi * t))  # 0.55↔1.0
    return Color(int(color.r * k), int(color.g * k), int(color.b * k))
