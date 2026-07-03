"""Internal documentation."""
from __future__ import annotations

import pytest

from argos.approval import ApprovalGate, ApprovalLevel
from argos.permissions.evaluator import DecisionMeta, evaluate, _apply_trust_semantics
from argos.permissions.config import PermissionsConfig, RuleEntry
from argos.permissions.trust_dial import TrustLevel


# ────────────────────────────────────────────────────────────────────
# ────────────────────────────────────────────────────────────────────

def _empty_config() -> PermissionsConfig:
    """Internal documentation."""
    return PermissionsConfig()


# ────────────────────────────────────────────────────────────────────
# ────────────────────────────────────────────────────────────────────

class TestEvaluatorL0AskReadonly:
    """Internal documentation."""

    def test_auto_level_action_becomes_ask_under_l0(self):
        """Internal documentation."""
        meta = evaluate(
            "read_file", {"path": "foo.txt"},
            gate_level=ApprovalLevel.AUTO,
            config=_empty_config(),
            ask_readonly=True,
        )
        assert meta.decision == "ask", f"L0 下 AUTO 级 read_file 应 ask，实际={meta.decision}"
        assert meta.trigger == "trust:L0 每步确认"

    def test_soft_allow_action_becomes_ask_under_l0(self):
        """Internal documentation."""
        cfg = PermissionsConfig(allow=(RuleEntry(tool="read_file", matcher=".*"),))
        meta = evaluate(
            "read_file", {"path": "foo.txt"},
            gate_level=ApprovalLevel.CONFIRM,
            config=cfg,
            ask_readonly=True,
        )
        assert meta.decision == "ask", f"L0 下 soft-allow read_file 应 ask，实际={meta.decision}"
        assert meta.trigger == "trust:L0 每步确认"

    def test_confirm_level_already_asks_no_change(self):
        """Internal documentation."""
        meta = evaluate(
            "read_file", {"path": "foo.txt"},
            gate_level=ApprovalLevel.CONFIRM,
            config=_empty_config(),
            ask_readonly=True,
        )
        assert meta.decision == "ask"

    def test_l0_does_not_affect_hard_deny(self):
        """Internal documentation."""
        meta = evaluate(
            "run_command", {"cmd": "rm -rf /"},
            gate_level=ApprovalLevel.CONFIRM,
            config=_empty_config(),
            ask_readonly=True,
        )
        assert meta.decision == "deny", f"hard rule 应 deny，实际={meta.decision}"
        assert meta.trigger.startswith("hard_rule:")

    def test_l0_does_not_affect_soft_deny(self):
        """Internal documentation."""
        cfg = PermissionsConfig(deny=(RuleEntry(tool="run_command", matcher="forbidden_cmd"),))
        meta = evaluate(
            "run_command", {"cmd": "forbidden_cmd"},
            gate_level=ApprovalLevel.CONFIRM,
            config=cfg,
            ask_readonly=True,
        )
        assert meta.decision == "deny"
        assert meta.trigger.startswith("soft_deny:")

    def test_l0_soft_allow_becomes_ask(self):
        """Internal documentation."""
        cfg = PermissionsConfig(allow=(RuleEntry(tool="web_search", matcher=".*"),))
        meta = evaluate(
            "web_search", {"query": "hello"},
            gate_level=ApprovalLevel.CONFIRM,
            config=cfg,
            ask_readonly=True,
        )
        assert meta.decision == "ask"
        assert meta.trigger == "trust:L0 每步确认"

    def test_l0_false_no_change(self):
        """Internal documentation."""
        cfg = PermissionsConfig(allow=(RuleEntry(tool="read_file", matcher=".*"),))
        meta = evaluate(
            "read_file", {"path": "a.txt"},
            gate_level=ApprovalLevel.AUTO,
            config=cfg,
            ask_readonly=False,
        )
        assert meta.decision == "approve"

    def test_l0_preserves_existing_ask(self):
        """Internal documentation."""
        cfg = PermissionsConfig(ask=(RuleEntry(tool="edit_file", matcher=".*"),))
        meta = evaluate(
            "edit_file", {"path": "b.py"},
            gate_level=ApprovalLevel.CONFIRM,
            config=cfg,
            ask_readonly=True,
        )
        assert meta.decision == "ask"


# ────────────────────────────────────────────────────────────────────
# ────────────────────────────────────────────────────────────────────

class TestGateL0Wiring:
    """Internal documentation."""

    def test_gate_l0_sets_ask_readonly_flag(self):
        gate = ApprovalGate()
        gate.set_trust_level(TrustLevel.L0_EVERY_STEP)
        assert gate._ask_readonly is True

    def test_gate_l0_evaluate_returns_ask_for_auto_level(self):
        """Internal documentation."""
        from argos.permissions.config import PermissionsConfig, RuleEntry
        gate = ApprovalGate()
        gate.set_trust_level(TrustLevel.L0_EVERY_STEP)
        gate._permissions_config = PermissionsConfig(
            allow=(RuleEntry(tool="read_file", matcher=".*"),)
        )
        meta = gate._evaluate("read_file", {"path": "x.txt"})
        assert meta is not None
        assert meta.decision == "ask"
        assert meta.trigger == "trust:L0 每步确认"

    def test_gate_l0_hard_rule_still_deny(self):
        """Internal documentation."""
        gate = ApprovalGate()
        gate.set_trust_level(TrustLevel.L0_EVERY_STEP)
        meta = gate._evaluate("run_command", {"cmd": "rm -rf /"})
        assert meta is not None
        assert meta.decision == "deny"


# ────────────────────────────────────────────────────────────────────
# ────────────────────────────────────────────────────────────────────

class TestEvaluatorL2ReversibleLookup:
    """Internal documentation."""

    def _eval_l2(self, action: str, reversible: "bool | None",
                 gate_level: ApprovalLevel = ApprovalLevel.AUTO) -> DecisionMeta:
        """Internal documentation."""
        def _lookup(a: str) -> "bool | None":
            return reversible
        return evaluate(
            action, {},
            gate_level=gate_level,
            config=_empty_config(),
            reversible_lookup=_lookup,
        )

    def test_reversible_true_approves(self):
        """Internal documentation."""
        meta = self._eval_l2("read_file", True)
        assert meta.decision == "approve", f"可逆动作应 approve，实际={meta.decision}"
        assert meta.trigger == "trust:L2 可逆放行"

    def test_reversible_false_asks(self):
        """Internal documentation."""
        meta = self._eval_l2("write_file", False)
        assert meta.decision == "ask", f"不可逆动作应 ask，实际={meta.decision}"
        assert "L2" in meta.reason

    def test_reversible_none_asks(self):
        """Internal documentation."""
        meta = self._eval_l2("mcp_call", None)
        assert meta.decision == "ask"
        assert "L2" in meta.reason

    def test_reversible_lookup_exception_asks(self):
        """Internal documentation."""
        def _bad_lookup(a: str) -> "bool | None":
            raise RuntimeError("DB 故障")
        meta = evaluate(
            "run_command", {},
            gate_level=ApprovalLevel.CONFIRM,
            config=_empty_config(),
            reversible_lookup=_bad_lookup,
        )
        assert meta.decision == "ask"

    def test_reversible_lookup_unknown_action_asks(self):
        """Internal documentation."""
        def _lookup(a: str) -> "bool | None":
            return None
        meta = evaluate(
            "some_unknown_tool", {},
            gate_level=ApprovalLevel.CONFIRM,
            config=_empty_config(),
            reversible_lookup=_lookup,
        )
        assert meta.decision == "ask"

    def test_l2_hard_deny_not_affected(self):
        """Internal documentation."""
        def _lookup(a: str) -> "bool | None":
            return True
        meta = evaluate(
            "run_command", {"cmd": "rm -rf /"},
            gate_level=ApprovalLevel.CONFIRM,
            config=_empty_config(),
            reversible_lookup=_lookup,
        )
        assert meta.decision == "deny"
        assert meta.trigger.startswith("hard_rule:")

    def test_no_reversible_lookup_no_change(self):
        """Internal documentation."""
        meta = evaluate(
            "read_file", {},
            gate_level=ApprovalLevel.CONFIRM,
            config=_empty_config(),
            reversible_lookup=None,
        )
        assert meta.decision == "ask"


# ────────────────────────────────────────────────────────────────────
# ────────────────────────────────────────────────────────────────────

class TestGateL2Wiring:
    """Internal documentation."""

    def _gate_l2(self, reversible: "bool | None") -> ApprovalGate:
        gate = ApprovalGate()
        gate.set_trust_level(TrustLevel.L2_IRREVERSIBLE_ONLY)
        gate.set_reversible_lookup(lambda a: reversible)
        return gate

    def test_l2_flag_set(self):
        gate = ApprovalGate()
        gate.set_trust_level(TrustLevel.L2_IRREVERSIBLE_ONLY)
        assert gate._reversible_check is True

    def test_l2_reversible_true_approves(self):
        """Internal documentation."""
        gate = self._gate_l2(True)
        meta = gate._evaluate("read_file", {"path": "x.txt"})
        assert meta is not None
        assert meta.decision == "approve"
        assert meta.trigger == "trust:L2 可逆放行"

    def test_l2_reversible_false_asks(self):
        """Internal documentation."""
        gate = self._gate_l2(False)
        meta = gate._evaluate("write_file", {"path": "x.txt"})
        assert meta is not None
        assert meta.decision == "ask"

    def test_l2_reversible_none_asks(self):
        """Internal documentation."""
        gate = self._gate_l2(None)
        meta = gate._evaluate("mcp_call", {})
        assert meta is not None
        assert meta.decision == "ask"

    def test_l2_no_lookup_injected_asks(self):
        """Internal documentation."""
        gate = ApprovalGate()
        gate.set_trust_level(TrustLevel.L2_IRREVERSIBLE_ONLY)
        meta = gate._evaluate("read_file", {"path": "x.txt"})
        assert meta is not None
        assert meta.decision == "ask"

    def test_l2_audit_trigger_label(self):
        """Internal documentation."""
        gate = self._gate_l2(True)
        meta = gate._evaluate("read_file", {})
        assert meta is not None
        assert "L2" in meta.trigger


# ────────────────────────────────────────────────────────────────────
# ────────────────────────────────────────────────────────────────────

class TestL2HardRuleImmune:
    """Internal documentation."""

    @pytest.mark.parametrize("cmd,action", [
        ("rm -rf /", "run_command"),
    ])
    def test_hard_rule_deny_survives_l2(self, cmd: str, action: str):
        gate = ApprovalGate()
        gate.set_trust_level(TrustLevel.L2_IRREVERSIBLE_ONLY)
        gate.set_reversible_lookup(lambda _: True)
        meta = gate._evaluate(action, {"cmd": cmd})
        assert meta is not None
        assert meta.decision == "deny"


# ────────────────────────────────────────────────────────────────────
# ────────────────────────────────────────────────────────────────────

class TestL4Unchanged:
    """Internal documentation."""

    def test_l4_ask_readonly_false(self):
        gate = ApprovalGate()
        gate.set_trust_level(TrustLevel.L4_AUTONOMOUS)
        assert gate._ask_readonly is False

    def test_l4_reversible_check_false(self):
        gate = ApprovalGate()
        gate.set_trust_level(TrustLevel.L4_AUTONOMOUS)
        assert gate._reversible_check is False

    def test_l4_level_is_auto(self):
        gate = ApprovalGate()
        gate.set_trust_level(TrustLevel.L4_AUTONOMOUS)
        assert gate.level is ApprovalLevel.AUTO


# ────────────────────────────────────────────────────────────────────
# ────────────────────────────────────────────────────────────────────

class TestTrustStatusAnnotation:
    """Internal documentation."""

    def test_app_py_no_wiring_annotation(self):
        """Internal documentation."""
        from pathlib import Path
        src = Path(__file__).parents[2] / "argos" / "tui" / "app.py"
        text = src.read_text(encoding="utf-8")
        assert "接线中" not in text, "tui/app.py 仍含接线中注解，应已摘除"

    def test_trust_dial_no_wiring_annotation(self):
        """Internal documentation."""
        from pathlib import Path
        src = Path(__file__).parents[2] / "argos" / "permissions" / "trust_dial.py"
        text = src.read_text(encoding="utf-8")
        assert "P2 未完成前退化 L1" not in text

    def test_approval_py_no_wiring_annotation(self):
        """Internal documentation."""
        from pathlib import Path
        src = Path(__file__).parents[2] / "argos" / "approval.py"
        text = src.read_text(encoding="utf-8")
        assert "当前 evaluator 路径无此字段" not in text


# ────────────────────────────────────────────────────────────────────
# ────────────────────────────────────────────────────────────────────

class TestApplyTrustSemantics:
    """Internal documentation."""

    def _meta(self, decision: str, trigger: str = "level:auto") -> DecisionMeta:
        return DecisionMeta(decision=decision, trigger=trigger)  # type: ignore[arg-type]

    def test_deny_unchanged_by_l0(self):
        meta = _apply_trust_semantics(
            self._meta("deny", "hard_rule:x"),
            action="run_command", ask_readonly=True, reversible_lookup=None
        )
        assert meta.decision == "deny"
        assert meta.trigger == "hard_rule:x"

    def test_deny_unchanged_by_l2(self):
        meta = _apply_trust_semantics(
            self._meta("deny", "hard_rule:y"),
            action="write_file", ask_readonly=False, reversible_lookup=lambda _: True
        )
        assert meta.decision == "deny"

    def test_l0_approve_to_ask(self):
        meta = _apply_trust_semantics(
            self._meta("approve"),
            action="read_file", ask_readonly=True, reversible_lookup=None
        )
        assert meta.decision == "ask"
        assert meta.trigger == "trust:L0 每步确认"

    def test_l0_ask_unchanged(self):
        meta = _apply_trust_semantics(
            self._meta("ask", "soft_ask:x"),
            action="edit_file", ask_readonly=True, reversible_lookup=None
        )
        assert meta.decision == "ask"
        assert meta.trigger == "soft_ask:x"

    def test_l2_true_approve(self):
        meta = _apply_trust_semantics(
            self._meta("approve"),
            action="read_file", ask_readonly=False, reversible_lookup=lambda _: True
        )
        assert meta.decision == "approve"
        assert meta.trigger == "trust:L2 可逆放行"

    def test_l2_false_ask(self):
        meta = _apply_trust_semantics(
            self._meta("approve"),
            action="write_file", ask_readonly=False, reversible_lookup=lambda _: False
        )
        assert meta.decision == "ask"

    def test_l2_none_ask(self):
        meta = _apply_trust_semantics(
            self._meta("approve"),
            action="mcp_call", ask_readonly=False, reversible_lookup=lambda _: None
        )
        assert meta.decision == "ask"

    def test_l2_existing_ask_not_promoted(self):
        """Internal documentation."""
        meta = _apply_trust_semantics(
            self._meta("ask", "soft_ask:dangerous"),
            action="run_command", ask_readonly=False, reversible_lookup=lambda _: True
        )
        assert meta.decision == "ask"

    def test_no_flags_passthrough(self):
        """Internal documentation."""
        orig = self._meta("approve", "soft_allow:x")
        meta = _apply_trust_semantics(
            orig, action="read_file", ask_readonly=False, reversible_lookup=None
        )
        assert meta is orig
