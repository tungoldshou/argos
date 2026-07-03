# argos/tui/theme.py
from __future__ import annotations

from textual.theme import Theme

ARGOS_NIGHT = Theme(
    name="argos-night",
    dark=True,
    primary="#D9A85C",
    secondary="#7AA2F7",
    accent="#D9A85C",             # = primary($eye)
    foreground="#C8CCDA",
    background="#0B0C10",
    surface="#0E0F15",
    panel="#1B1D29",
    success="#9ECE6A",            # $pass:verdict passed
    warning="#FF9E64",
    error="#F7768E",              # $fail:verdict failed
    boost="#23263A",
    variables={
        "abyss":        "#0B0C10",
        "well":         "#0E0F15",
        "stream":       "#13141B",
        "raise":        "#1B1D29",
        "raise-2":      "#23263A",
        "hairline":     "#23252E",
        "hairline-lit": "#2E3142",

        "ink-bright": "#ECEEF5",
        "ink":        "#C8CCDA",
        "ink-dim":    "#7E869C",
        "ink-faint":  "#6B7494",
        "ink-ghost":  "#3A4055",

        "eye-soft": "#A8854A",
        "eye":      "#D9A85C",
        "eye-glow": "#F0C078",

        "pass":         "#9ECE6A",
        "pass-weak":    "#73A857",
        "fail":         "#F7768E",
        "unverif":      "#FF9E64",
        "unverif-deep": "#9A6E2E",
        "cyan":         "#7DCFFF",

        "plan": "#7AA2F7",

        "block-cursor-foreground": "#0B0C10",
        "block-cursor-background": "#F0C078",

        "scrollbar":       "#1B1D29",   # = $raise
        "scrollbar-hover": "#23263A",   # = $raise-2

        "border": "#2E3142",            # = $hairline-lit

        "text-muted": "#7E869C",        # = $ink-dim
    },
)
