"""Internal documentation."""
from __future__ import annotations

import pytest

from argos.permissions.trust_dial import (
    TrustLevel,
    TRUST_CYCLE,
    hard_rules_immune,
    escalation_warning,
    next_in_cycle,
    to_approval_semantics,
)


# ─────────────────────────────────────────────────────────────────────────────
# ─────────────────────────────────────────────────────────────────────────────

class TestTrustLevelBasic:
    """Internal documentation."""

    def test_all_five_levels_exist(self):
        levels = list(TrustLevel)
        assert len(levels) == 5

    def test_integer_order(self):
        """Internal documentation."""
        assert (
            TrustLevel.L0_EVERY_STEP
            < TrustLevel.L1_DANGEROUS_ONLY
            < TrustLevel.L2_IRREVERSIBLE_ONLY
            < TrustLevel.L3_SESSION_TRUSTED
            < TrustLevel.L4_AUTONOMOUS
        )

    @pytest.mark.parametrize("level", list(TrustLevel))
    def test_label_human_nonempty(self, level: TrustLevel):
        assert level.label_human, f"{level} label_human 不得为空"

    @pytest.mark.parametrize("level", list(TrustLevel))
    def test_description_nonempty(self, level: TrustLevel):
        assert level.description, f"{level} description 不得为空"


# ─────────────────────────────────────────────────────────────────────────────
# ─────────────────────────────────────────────────────────────────────────────

class TestToApprovalSemantics:
    """Internal documentation."""

    def _sem(self, level: TrustLevel) -> dict:
        sem = to_approval_semantics(level)
        assert isinstance(sem, dict), "必须返回 dict"
        return sem

    # ── L0 ──────────────────────────────────────────────────────────────────

    def test_l0_approval_level_confirm(self):
        sem = self._sem(TrustLevel.L0_EVERY_STEP)
        assert sem["approval_level"] == "confirm"

    def test_l0_ask_readonly_true(self):
        """Internal documentation."""
        sem = self._sem(TrustLevel.L0_EVERY_STEP)
        assert sem.get("ask_readonly") is True

    def test_l0_reversible_check_false(self):
        sem = self._sem(TrustLevel.L0_EVERY_STEP)
        assert sem["reversible_check"] is False

    # ── L1 ──────────────────────────────────────────────────────────────────

    def test_l1_approval_level_confirm(self):
        sem = self._sem(TrustLevel.L1_DANGEROUS_ONLY)
        assert sem["approval_level"] == "confirm"

    def test_l1_ask_readonly_false(self):
        """Internal documentation."""
        sem = self._sem(TrustLevel.L1_DANGEROUS_ONLY)
        assert sem.get("ask_readonly") is False

    def test_l1_reversible_check_false(self):
        sem = self._sem(TrustLevel.L1_DANGEROUS_ONLY)
        assert sem["reversible_check"] is False

    # ── L2 ──────────────────────────────────────────────────────────────────

    def test_l2_approval_level_confirm(self):
        sem = self._sem(TrustLevel.L2_IRREVERSIBLE_ONLY)
        assert sem["approval_level"] == "confirm"

    def test_l2_reversible_check_true(self):
        """Internal documentation."""
        sem = self._sem(TrustLevel.L2_IRREVERSIBLE_ONLY)
        assert sem["reversible_check"] is True

    def test_l2_reversible_check_in_description(self):
        """Internal documentation."""
        sem = self._sem(TrustLevel.L2_IRREVERSIBLE_ONLY)
        desc = sem.get("description", "")
        assert "reversible" in desc.lower(), (
            f"L2 description 应提及 reversible 字段，实际: {desc!r}"
        )

    # ── L3 ──────────────────────────────────────────────────────────────────

    def test_l3_approval_level_accept_edits(self):
        sem = self._sem(TrustLevel.L3_SESSION_TRUSTED)
        assert sem["approval_level"] == "accept_edits"

    def test_l3_reversible_check_false(self):
        sem = self._sem(TrustLevel.L3_SESSION_TRUSTED)
        assert sem["reversible_check"] is False

    # ── L4 ──────────────────────────────────────────────────────────────────

    def test_l4_approval_level_auto(self):
        sem = self._sem(TrustLevel.L4_AUTONOMOUS)
        assert sem["approval_level"] == "auto"

    def test_l4_yolo_indicator(self):
        """Internal documentation."""
        sem = self._sem(TrustLevel.L4_AUTONOMOUS)
        assert sem.get("show_yolo_indicator") is True


    @pytest.mark.parametrize("level", list(TrustLevel))
    def test_hard_rules_immune_always_true(self, level: TrustLevel):
        """Internal documentation."""
        sem = to_approval_semantics(level)
        assert sem["hard_rules_immune"] is True, (
            f"{level} 的 to_approval_semantics 必须含 hard_rules_immune=True"
        )

    @pytest.mark.parametrize("level", list(TrustLevel))
    def test_no_bypass_hard_rules_field(self, level: TrustLevel):
        """Internal documentation."""
        sem = to_approval_semantics(level)
        forbidden_keys = {
            "skip_hard_rules", "bypass_hard_rules", "ignore_hard_rules",
            "disable_hard_rules", "override_hard_rules",
        }
        found = forbidden_keys & set(sem.keys())
        assert not found, f"{level} 映射含禁止字段: {found}"

    @pytest.mark.parametrize("level", list(TrustLevel))
    def test_description_nonempty(self, level: TrustLevel):
        sem = to_approval_semantics(level)
        assert sem.get("description"), f"{level} 映射 description 不得为空"


# ─────────────────────────────────────────────────────────────────────────────
# ─────────────────────────────────────────────────────────────────────────────

class TestHardRulesImmune:
    def test_returns_true(self):
        assert hard_rules_immune() is True

    def test_can_assert(self):
        """Internal documentation."""
        assert hard_rules_immune()

    def test_always_true_multiple_calls(self):
        """Internal documentation."""
        for _ in range(10):
            assert hard_rules_immune() is True


# ─────────────────────────────────────────────────────────────────────────────
# ─────────────────────────────────────────────────────────────────────────────

class TestEscalationWarning:
    """Internal documentation."""

    @pytest.mark.parametrize("from_l,to_l", [
        (TrustLevel.L0_EVERY_STEP,      TrustLevel.L1_DANGEROUS_ONLY),
        (TrustLevel.L0_EVERY_STEP,      TrustLevel.L2_IRREVERSIBLE_ONLY),
        (TrustLevel.L0_EVERY_STEP,      TrustLevel.L3_SESSION_TRUSTED),
        (TrustLevel.L0_EVERY_STEP,      TrustLevel.L4_AUTONOMOUS),
        (TrustLevel.L1_DANGEROUS_ONLY,  TrustLevel.L2_IRREVERSIBLE_ONLY),
        (TrustLevel.L1_DANGEROUS_ONLY,  TrustLevel.L4_AUTONOMOUS),
        (TrustLevel.L2_IRREVERSIBLE_ONLY, TrustLevel.L3_SESSION_TRUSTED),
        (TrustLevel.L2_IRREVERSIBLE_ONLY, TrustLevel.L4_AUTONOMOUS),
        (TrustLevel.L3_SESSION_TRUSTED, TrustLevel.L4_AUTONOMOUS),
    ])
    def test_escalation_warning_nonempty(self, from_l: TrustLevel, to_l: TrustLevel):
        """Internal documentation."""
        w = escalation_warning(from_l, to_l)
        assert w, (
            f"escalation_warning({from_l.name} → {to_l.name}) 必须非空，实际: {w!r}"
        )

    @pytest.mark.parametrize("from_l,to_l", [
        (TrustLevel.L1_DANGEROUS_ONLY,  TrustLevel.L0_EVERY_STEP),
        (TrustLevel.L4_AUTONOMOUS,      TrustLevel.L0_EVERY_STEP),
        (TrustLevel.L4_AUTONOMOUS,      TrustLevel.L3_SESSION_TRUSTED),
        (TrustLevel.L3_SESSION_TRUSTED, TrustLevel.L1_DANGEROUS_ONLY),
        (TrustLevel.L2_IRREVERSIBLE_ONLY, TrustLevel.L0_EVERY_STEP),
    ])
    def test_downgrade_returns_empty(self, from_l: TrustLevel, to_l: TrustLevel):
        """Internal documentation."""
        w = escalation_warning(from_l, to_l)
        assert w == "", (
            f"escalation_warning({from_l.name} → {to_l.name}) 降档应为空串，实际: {w!r}"
        )

    @pytest.mark.parametrize("level", list(TrustLevel))
    def test_same_level_returns_empty(self, level: TrustLevel):
        """Internal documentation."""
        w = escalation_warning(level, level)
        assert w == "", f"等档 escalation_warning({level.name}) 应为空串，实际: {w!r}"

    def test_l4_warning_mentions_hard_rules(self):
        """Internal documentation."""
        w = escalation_warning(TrustLevel.L0_EVERY_STEP, TrustLevel.L4_AUTONOMOUS)
        assert "HARD" in w or "hard" in w.lower() or "硬规" in w, (
            f"升到 L4 的警示应提及 HARD RULES，实际: {w!r}"
        )

    def test_warning_mentions_what_is_relaxed(self):
        """Internal documentation."""
        w = escalation_warning(TrustLevel.L0_EVERY_STEP, TrustLevel.L1_DANGEROUS_ONLY)
        assert len(w) > 20, f"警示文案过短，可能没有实质内容: {w!r}"


# ─────────────────────────────────────────────────────────────────────────────
# ─────────────────────────────────────────────────────────────────────────────

class TestThreeModeLayer:
    """Internal documentation."""

    def test_mode_names_for_visible_modes(self):
        assert TrustLevel.L1_DANGEROUS_ONLY.mode_name == "Cautious"
        assert TrustLevel.L3_SESSION_TRUSTED.mode_name == "Trusted"
        assert TrustLevel.L4_AUTONOMOUS.mode_name == "Autonomous"

    def test_mode_name_paranoid_and_deprecated(self):
        assert TrustLevel.L0_EVERY_STEP.mode_name == "Paranoid"
        assert TrustLevel.L2_IRREVERSIBLE_ONLY.mode_name == "Irreversible-only"

    @pytest.mark.parametrize("level", list(TrustLevel))
    def test_mode_name_nonempty(self, level: TrustLevel):
        assert level.mode_name, f"{level} mode_name 不得为空"

    def test_cycle_is_three_visible_modes(self):
        assert TRUST_CYCLE == (
            TrustLevel.L1_DANGEROUS_ONLY,
            TrustLevel.L3_SESSION_TRUSTED,
            TrustLevel.L4_AUTONOMOUS,
        )
        assert TrustLevel.L0_EVERY_STEP not in TRUST_CYCLE
        assert TrustLevel.L2_IRREVERSIBLE_ONLY not in TRUST_CYCLE

    def test_next_in_cycle_wraps_three_modes(self):
        assert next_in_cycle(TrustLevel.L1_DANGEROUS_ONLY) is TrustLevel.L3_SESSION_TRUSTED
        assert next_in_cycle(TrustLevel.L3_SESSION_TRUSTED) is TrustLevel.L4_AUTONOMOUS
        assert next_in_cycle(TrustLevel.L4_AUTONOMOUS) is TrustLevel.L1_DANGEROUS_ONLY

    def test_next_in_cycle_normalizes_offcycle_levels(self):
        assert next_in_cycle(TrustLevel.L0_EVERY_STEP) is TrustLevel.L1_DANGEROUS_ONLY
        assert next_in_cycle(TrustLevel.L2_IRREVERSIBLE_ONLY) is TrustLevel.L3_SESSION_TRUSTED

    def test_full_cycle_returns_to_start(self):
        lvl = TrustLevel.L1_DANGEROUS_ONLY
        for _ in range(len(TRUST_CYCLE)):
            lvl = next_in_cycle(lvl)
        assert lvl is TrustLevel.L1_DANGEROUS_ONLY
