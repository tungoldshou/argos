from __future__ import annotations

import enum
from typing import Any

from argos.i18n import t


# ─────────────────────────────────────────────────────────────────────────────
# ─────────────────────────────────────────────────────────────────────────────

class TrustLevel(enum.IntEnum):
    L0_EVERY_STEP     = 0
    L1_DANGEROUS_ONLY = 1
    L2_IRREVERSIBLE_ONLY = 2
    L3_SESSION_TRUSTED = 3
    L4_AUTONOMOUS     = 4

    @property
    def label_human(self) -> str:
        return t(_HUMAN_LABELS[self])

    @property
    def description(self) -> str:
        return t(_DESCRIPTIONS[self])

    @property
    def mode_name(self) -> str:
        return _MODE_NAMES[self]


# ─────────────────────────────────────────────────────────────────────────────
# ─────────────────────────────────────────────────────────────────────────────

_MODE_NAMES: dict[TrustLevel, str] = {
    TrustLevel.L0_EVERY_STEP:        "Paranoid",
    TrustLevel.L1_DANGEROUS_ONLY:    "Cautious",
    TrustLevel.L2_IRREVERSIBLE_ONLY: "Irreversible-only",
    TrustLevel.L3_SESSION_TRUSTED:   "Trusted",
    TrustLevel.L4_AUTONOMOUS:        "Autonomous",
}

TRUST_CYCLE: tuple[TrustLevel, ...] = (
    TrustLevel.L1_DANGEROUS_ONLY,
    TrustLevel.L3_SESSION_TRUSTED,
    TrustLevel.L4_AUTONOMOUS,
)


def next_in_cycle(level: TrustLevel) -> TrustLevel:
    if level not in TRUST_CYCLE:
        if level is TrustLevel.L0_EVERY_STEP:
            return TrustLevel.L1_DANGEROUS_ONLY
        return TrustLevel.L3_SESSION_TRUSTED
    idx = TRUST_CYCLE.index(level)
    return TRUST_CYCLE[(idx + 1) % len(TRUST_CYCLE)]


_HUMAN_LABELS: dict[TrustLevel, str] = {
    TrustLevel.L0_EVERY_STEP:        "perm.label.l0",
    TrustLevel.L1_DANGEROUS_ONLY:    "perm.label.l1",
    TrustLevel.L2_IRREVERSIBLE_ONLY: "perm.label.l2",
    TrustLevel.L3_SESSION_TRUSTED:   "perm.label.l3",
    TrustLevel.L4_AUTONOMOUS:        "perm.label.l4",
}

_DESCRIPTIONS: dict[TrustLevel, str] = {
    TrustLevel.L0_EVERY_STEP:        "perm.desc.l0",
    TrustLevel.L1_DANGEROUS_ONLY:    "perm.desc.l1",
    TrustLevel.L2_IRREVERSIBLE_ONLY: "perm.desc.l2",
    TrustLevel.L3_SESSION_TRUSTED:   "perm.desc.l3",
    TrustLevel.L4_AUTONOMOUS:        "perm.desc.l4",
}


# ─────────────────────────────────────────────────────────────────────────────
# ─────────────────────────────────────────────────────────────────────────────

_AL_OBSERVE      = "observe"        # ApprovalLevel.OBSERVE
_AL_CONFIRM      = "confirm"        # ApprovalLevel.CONFIRM
_AL_ACCEPT_EDITS = "accept_edits"   # ApprovalLevel.ACCEPT_EDITS
_AL_AUTO         = "auto"           # ApprovalLevel.AUTO


def to_approval_semantics(level: TrustLevel) -> dict[str, Any]:
    _base: dict[str, Any] = {
        "hard_rules_immune": True,
    }

    if level is TrustLevel.L0_EVERY_STEP:
        return {
            **_base,
            "approval_level": _AL_CONFIRM,
            "description": t("perm.sem.desc.l0"),
            "reversible_check": False,
            "ask_readonly": True,
        }

    if level is TrustLevel.L1_DANGEROUS_ONLY:
        return {
            **_base,
            "approval_level": _AL_CONFIRM,
            "description": t("perm.sem.desc.l1"),
            "reversible_check": False,
            "ask_readonly": False,
            "low_risk_auto": True,
        }

    if level is TrustLevel.L2_IRREVERSIBLE_ONLY:
        return {
            **_base,
            "approval_level": _AL_CONFIRM,
            "description": t("perm.sem.desc.l2"),
            "reversible_check": True,
            "ask_readonly": False,
        }

    if level is TrustLevel.L3_SESSION_TRUSTED:
        return {
            **_base,
            "approval_level": _AL_ACCEPT_EDITS,
            "description": t("perm.sem.desc.l3"),
            "reversible_check": False,
            "ask_readonly": False,
        }

    if level is TrustLevel.L4_AUTONOMOUS:
        return {
            **_base,
            "approval_level": _AL_AUTO,
            "description": t("perm.sem.desc.l4"),
            "reversible_check": False,
            "ask_readonly": False,
            "show_yolo_indicator": True,
        }

    return {**_base, "approval_level": _AL_CONFIRM,
            "description": t("perm.sem.desc.unknown", level=level),
            "reversible_check": False, "ask_readonly": False}


# ─────────────────────────────────────────────────────────────────────────────
# ─────────────────────────────────────────────────────────────────────────────

def hard_rules_immune() -> bool:
    return True


# ─────────────────────────────────────────────────────────────────────────────
# ─────────────────────────────────────────────────────────────────────────────

_LEVEL_RELAXED_DESCRIPTION: dict[TrustLevel, str] = {
    TrustLevel.L0_EVERY_STEP:        "perm.relaxed.l0",
    TrustLevel.L1_DANGEROUS_ONLY:    "perm.relaxed.l1",
    TrustLevel.L2_IRREVERSIBLE_ONLY: "perm.relaxed.l2",
    TrustLevel.L3_SESSION_TRUSTED:   "perm.relaxed.l3",
    TrustLevel.L4_AUTONOMOUS:        "perm.relaxed.l4",
}


def escalation_warning(from_level: TrustLevel, to_level: TrustLevel) -> str:
    if int(to_level) <= int(from_level):
        return ""

    from_desc = t(_LEVEL_RELAXED_DESCRIPTION[from_level])
    to_label = to_level.label_human

    if to_level is TrustLevel.L4_AUTONOMOUS:
        return t("perm.escalation.to_l4", to_label=to_label, from_desc=from_desc)

    return t("perm.escalation.generic", from_desc=from_desc, to_label=to_label)
