"""Internal documentation."""
from __future__ import annotations

import asyncio
import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from argos.approval import ApprovalGate, ApprovalLevel
from argos.permissions.trust_dial import (
    TrustLevel,
    escalation_warning,
    hard_rules_immune,
    to_approval_semantics,
)


# ─────────────────────────────────────────────────────────────────────────────
# ─────────────────────────────────────────────────────────────────────────────

class TestGateSetTrustLevel:
    """Internal documentation."""

    def _gate(self) -> ApprovalGate:
        return ApprovalGate()

    @pytest.mark.parametrize("trust,expected_level", [
        (TrustLevel.L0_EVERY_STEP,      ApprovalLevel.CONFIRM),
        (TrustLevel.L1_DANGEROUS_ONLY,  ApprovalLevel.CONFIRM),
        (TrustLevel.L2_IRREVERSIBLE_ONLY, ApprovalLevel.CONFIRM),
        (TrustLevel.L3_SESSION_TRUSTED, ApprovalLevel.ACCEPT_EDITS),
        (TrustLevel.L4_AUTONOMOUS,      ApprovalLevel.AUTO),
    ])
    def test_approval_level_written(self, trust: TrustLevel, expected_level: ApprovalLevel):
        """Internal documentation."""
        gate = self._gate()
        gate.set_trust_level(trust)
        assert gate.level is expected_level, (
            f"trust={trust.name} 应映射到 {expected_level.name}，实际={gate.level.name}"
        )

    def test_l0_sets_ask_readonly(self):
        """Internal documentation."""
        gate = self._gate()
        gate.set_trust_level(TrustLevel.L0_EVERY_STEP)
        assert getattr(gate, "_ask_readonly", False) is True

    def test_l1_ask_readonly_false(self):
        """Internal documentation."""
        gate = self._gate()
        gate.set_trust_level(TrustLevel.L1_DANGEROUS_ONLY)
        assert getattr(gate, "_ask_readonly", False) is False

    def test_l4_level_is_auto(self):
        """Internal documentation."""
        gate = self._gate()
        gate.set_trust_level(TrustLevel.L4_AUTONOMOUS)
        assert gate.level is ApprovalLevel.AUTO

    def test_no_bypass_hard_rules_field_in_semantics(self):
        """Internal documentation."""
        for trust in TrustLevel:
            sem = to_approval_semantics(trust)
            assert sem["hard_rules_immune"] is True, (
                f"{trust.name} 的 semantics.hard_rules_immune 不是 True"
            )

    def test_set_trust_level_idempotent(self):
        """Internal documentation."""
        gate = self._gate()
        gate.set_trust_level(TrustLevel.L3_SESSION_TRUSTED)
        gate.set_trust_level(TrustLevel.L3_SESSION_TRUSTED)
        assert gate.level is ApprovalLevel.ACCEPT_EDITS

    def test_set_trust_level_allows_downgrade(self):
        """Internal documentation."""
        gate = self._gate()
        gate.set_trust_level(TrustLevel.L4_AUTONOMOUS)
        assert gate.level is ApprovalLevel.AUTO
        gate.set_trust_level(TrustLevel.L1_DANGEROUS_ONLY)
        assert gate.level is ApprovalLevel.CONFIRM


# ─────────────────────────────────────────────────────────────────────────────
# ─────────────────────────────────────────────────────────────────────────────

class TestHardRulesContractUnderL4:
    """Internal documentation."""

    def test_hard_rules_immune_returns_true(self):
        assert hard_rules_immune() is True

    @pytest.mark.parametrize("trust", list(TrustLevel))
    def test_hard_rules_immune_all_levels(self, trust: TrustLevel):
        """Internal documentation."""
        sem = to_approval_semantics(trust)
        assert sem["hard_rules_immune"] is True

    def test_l4_semantics_no_bypass_hard_rules(self):
        """Internal documentation."""
        sem = to_approval_semantics(TrustLevel.L4_AUTONOMOUS)
        assert sem.get("bypass_hard_rules") is None
        assert sem["approval_level"] == "auto"
        assert sem["hard_rules_immune"] is True

    def test_l4_gate_hard_rules_immune_survives(self):
        """Internal documentation."""
        gate = ApprovalGate()
        gate.set_trust_level(TrustLevel.L4_AUTONOMOUS)
        assert gate.level is ApprovalLevel.AUTO
        assert hard_rules_immune() is True


# ─────────────────────────────────────────────────────────────────────────────
# ─────────────────────────────────────────────────────────────────────────────

class TestEscalationWarningFlow:
    """Internal documentation."""

    @pytest.mark.parametrize("from_l,to_l", [
        (TrustLevel.L0_EVERY_STEP,      TrustLevel.L1_DANGEROUS_ONLY),
        (TrustLevel.L0_EVERY_STEP,      TrustLevel.L4_AUTONOMOUS),
        (TrustLevel.L1_DANGEROUS_ONLY,  TrustLevel.L2_IRREVERSIBLE_ONLY),
        (TrustLevel.L1_DANGEROUS_ONLY,  TrustLevel.L3_SESSION_TRUSTED),
        (TrustLevel.L1_DANGEROUS_ONLY,  TrustLevel.L4_AUTONOMOUS),
        (TrustLevel.L2_IRREVERSIBLE_ONLY, TrustLevel.L3_SESSION_TRUSTED),
        (TrustLevel.L3_SESSION_TRUSTED,  TrustLevel.L4_AUTONOMOUS),
    ])
    def test_escalation_warning_nonempty_on_upgrade(self, from_l: TrustLevel, to_l: TrustLevel):
        """Internal documentation."""
        warning = escalation_warning(from_l, to_l)
        assert warning, f"升档 {from_l.name}→{to_l.name} 应有非空警示，实际为空"

    @pytest.mark.parametrize("from_l,to_l", [
        (TrustLevel.L4_AUTONOMOUS,      TrustLevel.L3_SESSION_TRUSTED),
        (TrustLevel.L3_SESSION_TRUSTED, TrustLevel.L1_DANGEROUS_ONLY),
        (TrustLevel.L2_IRREVERSIBLE_ONLY, TrustLevel.L0_EVERY_STEP),
        (TrustLevel.L1_DANGEROUS_ONLY,  TrustLevel.L1_DANGEROUS_ONLY),
    ])
    def test_escalation_warning_empty_on_downgrade_or_same(self, from_l: TrustLevel, to_l: TrustLevel):
        """Internal documentation."""
        warning = escalation_warning(from_l, to_l)
        assert warning == "", f"降档/同档 {from_l.name}→{to_l.name} 应返回空串，实际：{warning!r}"

    def test_l4_warning_contains_hard_rules_mention(self):
        """Internal documentation."""
        warning = escalation_warning(TrustLevel.L0_EVERY_STEP, TrustLevel.L4_AUTONOMOUS)
        assert "HARD RULES" in warning or "hard rules" in warning.lower(), (
            "L4 升档警示应提及 HARD RULES"
        )


# ─────────────────────────────────────────────────────────────────────────────
# ─────────────────────────────────────────────────────────────────────────────

class TestSlashCommandRegistration:
    """Internal documentation."""

    def test_yolo_still_known(self):
        from argos.tui.commands import parse_slash
        cmd = parse_slash("/yolo")
        assert cmd is not None
        assert cmd.known is True
        assert cmd.name == "yolo"

    def test_trust_now_known(self):
        from argos.tui.commands import parse_slash
        cmd = parse_slash("/trust l3")
        assert cmd is not None
        assert cmd.known is True
        assert cmd.name == "trust"
        assert cmd.arg == "l3"

    def test_trust_status_known(self):
        from argos.tui.commands import parse_slash
        cmd = parse_slash("/trust status")
        assert cmd is not None
        assert cmd.known is True

    def test_trust_no_arg_known(self):
        from argos.tui.commands import parse_slash
        cmd = parse_slash("/trust")
        assert cmd is not None
        assert cmd.known is True
        assert cmd.arg == ""

    def test_trust_in_command_help(self):
        from argos.tui.commands import COMMAND_HELP
        assert "trust" in COMMAND_HELP

    def test_yolo_help_mentions_trust(self):
        from argos.tui.commands import COMMAND_HELP
        assert "trust" in COMMAND_HELP["yolo"]

    def test_match_commands_includes_trust(self):
        from argos.tui.commands import match_commands
        results = match_commands("/tru")
        names = [n for n, _ in results]
        assert "trust" in names


# ─────────────────────────────────────────────────────────────────────────────
# ─────────────────────────────────────────────────────────────────────────────

class TestDaemonTrustLevelParam:
    """Internal documentation."""

    def _make_server(self):
        """Internal documentation."""
        from argos.daemon.server import DaemonHTTPServer
        mgr = MagicMock()
        mgr.create_run = AsyncMock(return_value="run-test-001")
        mgr.store = MagicMock()
        mgr.store.append = MagicMock()
        mgr.fanout = AsyncMock()
        mgr.get_run = MagicMock(return_value=None)

        registry = MagicMock()
        registry.has_capacity = MagicMock(return_value=True)
        registry.acquire_slot = AsyncMock()
        registry.release_slot = MagicMock()
        registry.register = AsyncMock()
        registry.active_count = 0
        registry.max_concurrent = 4

        worktree = MagicMock()

        server = DaemonHTTPServer.__new__(DaemonHTTPServer)
        server._manager = mgr
        server._registry = registry
        server._worktree = worktree
        server._workers = {}
        server._components = None
        server._loop_factory = None
        server._gate = ApprovalGate()
        server._ledger_store = None
        return server

    def test_no_trust_level_gate_unchanged(self):
        """Internal documentation."""
        gate = ApprovalGate()
        assert gate.level is ApprovalLevel.CONFIRM
        trust_str = None
        if trust_str:
            from argos.permissions.trust_dial import TrustLevel
            gate.set_trust_level(TrustLevel[trust_str])
        assert gate.level is ApprovalLevel.CONFIRM

    @pytest.mark.parametrize("trust_name,expected_al", [
        ("L0_EVERY_STEP",      ApprovalLevel.CONFIRM),
        ("L1_DANGEROUS_ONLY",  ApprovalLevel.CONFIRM),
        ("L2_IRREVERSIBLE_ONLY", ApprovalLevel.CONFIRM),
        ("L3_SESSION_TRUSTED", ApprovalLevel.ACCEPT_EDITS),
        ("L4_AUTONOMOUS",      ApprovalLevel.AUTO),
    ])
    def test_valid_trust_name_applied(self, trust_name: str, expected_al: ApprovalLevel):
        """Internal documentation."""
        gate = ApprovalGate()
        from argos.permissions.trust_dial import TrustLevel
        gate.set_trust_level(TrustLevel[trust_name])
        assert gate.level is expected_al

    def test_invalid_trust_name_does_not_raise(self):
        """Internal documentation."""
        gate = ApprovalGate()
        original_level = gate.level
        trust_str = "INVALID_LEVEL_XYZ"
        try:
            from argos.permissions.trust_dial import TrustLevel
            tl = TrustLevel[trust_str]
            gate.set_trust_level(tl)
        except KeyError:
            pass
        assert gate.level is original_level, "非法枚举名不应修改 gate.level"

    def test_empty_trust_level_no_effect(self):
        """Internal documentation."""
        gate = ApprovalGate()
        trust_str = ""
        if trust_str:
            from argos.permissions.trust_dial import TrustLevel
            gate.set_trust_level(TrustLevel[trust_str])
        assert gate.level is ApprovalLevel.CONFIRM


# ─────────────────────────────────────────────────────────────────────────────
# ─────────────────────────────────────────────────────────────────────────────

class TestNoTrustLevelBackwardCompat:
    """Internal documentation."""

    def test_gate_default_is_confirm(self):
        gate = ApprovalGate()
        assert gate.level is ApprovalLevel.CONFIRM

    def test_set_level_still_works(self):
        """Internal documentation."""
        gate = ApprovalGate()
        gate.set_level(ApprovalLevel.AUTO)
        assert gate.level is ApprovalLevel.AUTO

    def test_set_trust_level_does_not_break_set_level(self):
        """Internal documentation."""
        gate = ApprovalGate()
        gate.set_trust_level(TrustLevel.L4_AUTONOMOUS)
        gate.set_level(ApprovalLevel.CONFIRM)
        assert gate.level is ApprovalLevel.CONFIRM

    def test_hard_rules_immune_always_true_regardless_of_gate_state(self):
        """Internal documentation."""
        gate = ApprovalGate()
        gate.set_trust_level(TrustLevel.L4_AUTONOMOUS)
        assert hard_rules_immune() is True
        gate.set_trust_level(TrustLevel.L0_EVERY_STEP)
        assert hard_rules_immune() is True
