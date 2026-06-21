"""工作态阶段映射边缘光(spec §工作态边缘光)。颜色=真实 phase/verdict,非随机彩虹。"""
from __future__ import annotations

from textual.color import Color

IDLE_BORDER = Color(46, 49, 66)        # #2E3142 = $hairline-lit(idle 灭,v3 token 对齐)
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


def verdict_color_self_aware(status: str, self_verified: bool = False) -> Color:
    """E4 防火墙:self_verified=True 的 passed 降级为 WARNING(暖橙),
    绝不冒充 SUCCESS 绿色(用户级 verify 才有资格绿)。
    """
    if status == "passed" and self_verified:
        return WARNING
    return verdict_color(status)


def verdict_border_color(verdict) -> Color:
    """从 Verdict 对象派生边框光颜色(CONTRACT A)。

    no_test==True:无机检态返回 IDLE_BORDER 中性灰,绝不染橙警告色。
    真 unverifiable(篡改/超时等):返回 WARNING 暖橙(三重冗余:◔ + 橙 + 文字)。
    其余态:按 status / self_verified 正常映射。
    """
    # CONTRACT A:no_test 字段由 CORE 添加;getattr 防御性兼容旧 Verdict 对象。
    if getattr(verdict, "no_test", False):
        return IDLE_BORDER   # 中性灰 — 无机检不是警告,只是"未配 verify"
    return verdict_color_self_aware(verdict.status, getattr(verdict, "self_verified", False))


def breathe(color: Color, t: float) -> Color:
    """t∈[0,1] 正弦相位 → 在 color 与略暗之间插值(呼吸)。"""
    import math

    k = 0.55 + 0.45 * (0.5 - 0.5 * math.cos(2 * math.pi * t))  # 0.55↔1.0
    return Color(int(color.r * k), int(color.g * k), int(color.b * k))
