# argos_agent/tui/theme.py
"""argos-night:Tokyo-Night 系暗色主题 + 唯一暖橙强调(spec §配色)。
色花在意义上:暖橙=唯一强调(⏺/spinner/logo/›);绿/红/暖橙只给 verdict 与 diff。"""
from __future__ import annotations

from textual.theme import Theme

ARGOS_NIGHT = Theme(
    name="argos-night",
    primary="#E0AF68",     # 暖橙:唯一强调(focus 边框/Input/›)
    secondary="#9D7CD8",   # 紫(备用:plan 阶段等)
    accent="#E0AF68",      # 暖橙(⏺/spinner/active phase)
    foreground="#C0CAF5",  # 散文亮白
    background="#16161E",
    surface="#1A1B26",
    panel="#24283B",
    success="#9ECE6A",     # verdict passed / diff +
    warning="#E0AF68",     # verdict unverifiable / escalation(暖橙同源)
    error="#F7768E",       # verdict failed / diff -
    dark=True,
    variables={
        "text-muted": "#565F89",   # user 回显/次要/分隔线/折叠提示
        # TUI v2:输入光标对齐唯一强调色(块光标橙底深字,不再用默认反白)
        "block-cursor-foreground": "#16161E",
        "block-cursor-background": "#E0AF68",
    },
)
