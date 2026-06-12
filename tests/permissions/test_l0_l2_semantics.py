"""L0/L2 Trust Dial 细粒度语义真生效测试。

覆盖：
A. L0(ask_readonly=True)— evaluator 层：低风险动作 approve → ask；hard rule deny 不变。
B. L0 通过 gate._evaluate 透传：gate 设 L0 后，只读动作真 ask。
C. L2(reversible_lookup)— evaluator 层：
     reversible=True  → approve(trigger="trust:L2 可逆放行")
     reversible=False → ask
     reversible=None  → ask(保守)
     lookup 出错       → ask(fail-closed)
D. L2 通过 gate._evaluate 透传：gate 设 L2 + 注入 lookup 后真生效。
E. L2 下 hard rule deny 不被降级。
F. L4 行为零变更（无 ask_readonly，无 reversible_lookup）。
G. /trust status 注解不再含"接线中"字样。
"""
from __future__ import annotations

import pytest

from argos_agent.approval import ApprovalGate, ApprovalLevel
from argos_agent.permissions.evaluator import DecisionMeta, evaluate, _apply_trust_semantics
from argos_agent.permissions.config import PermissionsConfig, RuleEntry
from argos_agent.permissions.trust_dial import TrustLevel


# ────────────────────────────────────────────────────────────────────
# 共用 fixture
# ────────────────────────────────────────────────────────────────────

def _empty_config() -> PermissionsConfig:
    """空白权限配置(无软规则,default_level=None)。"""
    return PermissionsConfig()


# ────────────────────────────────────────────────────────────────────
# A. evaluator 层 — L0 ask_readonly
# ────────────────────────────────────────────────────────────────────

class TestEvaluatorL0AskReadonly:
    """evaluator.evaluate(ask_readonly=True) 把 approve 升格 ask。"""

    def test_auto_level_action_becomes_ask_under_l0(self):
        """gate_level=AUTO 时本会 approve 的动作在 L0 下变 ask。"""
        meta = evaluate(
            "read_file", {"path": "foo.txt"},
            gate_level=ApprovalLevel.AUTO,
            config=_empty_config(),
            ask_readonly=True,
        )
        assert meta.decision == "ask", f"L0 下 AUTO 级 read_file 应 ask，实际={meta.decision}"
        assert meta.trigger == "trust:L0 每步确认"

    def test_soft_allow_action_becomes_ask_under_l0(self):
        """soft allow 命中的 approve 在 L0 下变 ask（只读也问）。"""
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
        """gate_level=CONFIRM + 无规则 → 已经 ask；L0 的效果体现在 trigger 源头，但 decision 一样。"""
        meta = evaluate(
            "read_file", {"path": "foo.txt"},
            gate_level=ApprovalLevel.CONFIRM,
            config=_empty_config(),
            ask_readonly=True,
        )
        # CONFIRM 档默认已是 ask；L0 不改变 ask 的 decision
        assert meta.decision == "ask"

    def test_l0_does_not_affect_hard_deny(self):
        """L0 ask_readonly 不改变 hard rule deny（rm -rf 仍 deny）。"""
        meta = evaluate(
            "run_command", {"cmd": "rm -rf /"},
            gate_level=ApprovalLevel.CONFIRM,
            config=_empty_config(),
            ask_readonly=True,
        )
        assert meta.decision == "deny", f"hard rule 应 deny，实际={meta.decision}"
        assert meta.trigger.startswith("hard_rule:")

    def test_l0_does_not_affect_soft_deny(self):
        """L0 ask_readonly 不改变 soft deny 规则命中结果。"""
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
        """L0 下 soft allow 命中的 approve → ask（只读也问）。"""
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
        """ask_readonly=False(默认)时，软 allow 的 approve 保持 approve。"""
        cfg = PermissionsConfig(allow=(RuleEntry(tool="read_file", matcher=".*"),))
        meta = evaluate(
            "read_file", {"path": "a.txt"},
            gate_level=ApprovalLevel.AUTO,
            config=cfg,
            ask_readonly=False,
        )
        assert meta.decision == "approve"

    def test_l0_preserves_existing_ask(self):
        """soft ask 规则命中产生的 ask 在 L0 下维持 ask（不变）。"""
        cfg = PermissionsConfig(ask=(RuleEntry(tool="edit_file", matcher=".*"),))
        meta = evaluate(
            "edit_file", {"path": "b.py"},
            gate_level=ApprovalLevel.CONFIRM,
            config=cfg,
            ask_readonly=True,
        )
        assert meta.decision == "ask"


# ────────────────────────────────────────────────────────────────────
# B. gate 层 — L0 透传
# ────────────────────────────────────────────────────────────────────

class TestGateL0Wiring:
    """gate 设 L0 后 _evaluate 真透传 ask_readonly=True。"""

    def test_gate_l0_sets_ask_readonly_flag(self):
        gate = ApprovalGate()
        gate.set_trust_level(TrustLevel.L0_EVERY_STEP)
        assert gate._ask_readonly is True

    def test_gate_l0_evaluate_returns_ask_for_auto_level(self):
        """L0 档位下，AUTO 级默认放行的动作应被 ask_readonly 升格为 ask。

        set_trust_level(L0) 写入 CONFIRM，但 evaluator 的 ask_readonly=True 会把 AUTO
        级 soft-allow approve 升格 ask。用 soft-allow 规则触发 approve 来验证 L0 效果。
        """
        from argos_agent.permissions.config import PermissionsConfig, RuleEntry
        gate = ApprovalGate()
        gate.set_trust_level(TrustLevel.L0_EVERY_STEP)
        # 注入允许 read_file 的 permissions_config
        gate._permissions_config = PermissionsConfig(
            allow=(RuleEntry(tool="read_file", matcher=".*"),)
        )
        meta = gate._evaluate("read_file", {"path": "x.txt"})
        assert meta is not None
        assert meta.decision == "ask"
        assert meta.trigger == "trust:L0 每步确认"

    def test_gate_l0_hard_rule_still_deny(self):
        """L0 档位下 hard rule 动作仍 deny。"""
        gate = ApprovalGate()
        gate.set_trust_level(TrustLevel.L0_EVERY_STEP)
        meta = gate._evaluate("run_command", {"cmd": "rm -rf /"})
        assert meta is not None
        assert meta.decision == "deny"


# ────────────────────────────────────────────────────────────────────
# C. evaluator 层 — L2 reversible_lookup
# ────────────────────────────────────────────────────────────────────

class TestEvaluatorL2ReversibleLookup:
    """evaluator.evaluate(reversible_lookup=...) 对动作可逆性正确决策。"""

    def _eval_l2(self, action: str, reversible: "bool | None",
                 gate_level: ApprovalLevel = ApprovalLevel.AUTO) -> DecisionMeta:
        """构造 reversible_lookup 并调用 evaluate。gate_level=AUTO 使默认路径产生 approve。"""
        def _lookup(a: str) -> "bool | None":
            return reversible
        return evaluate(
            action, {},
            gate_level=gate_level,
            config=_empty_config(),
            reversible_lookup=_lookup,
        )

    def test_reversible_true_approves(self):
        """reversible=True + gate_level=AUTO → approve(trigger='trust:L2 可逆放行')。"""
        meta = self._eval_l2("read_file", True)
        assert meta.decision == "approve", f"可逆动作应 approve，实际={meta.decision}"
        assert meta.trigger == "trust:L2 可逆放行"

    def test_reversible_false_asks(self):
        """reversible=False + gate_level=AUTO → 保守 ask（升格 approve → ask）。"""
        meta = self._eval_l2("write_file", False)
        assert meta.decision == "ask", f"不可逆动作应 ask，实际={meta.decision}"
        assert "L2" in meta.reason

    def test_reversible_none_asks(self):
        """reversible=None(未知) + gate_level=AUTO → 保守 ask。"""
        meta = self._eval_l2("mcp_call", None)
        assert meta.decision == "ask"
        assert "L2" in meta.reason

    def test_reversible_lookup_exception_asks(self):
        """lookup 抛异常 → ask(fail-closed)。"""
        def _bad_lookup(a: str) -> "bool | None":
            raise RuntimeError("DB 故障")
        meta = evaluate(
            "run_command", {},
            gate_level=ApprovalLevel.CONFIRM,
            config=_empty_config(),
            reversible_lookup=_bad_lookup,
        )
        # run_command hard rule 先拦截(rm -rf 测试已验过);此处用普通无规则命中的情形:
        # hard rule 不命中(无 cmd 参数) → 走到 reversible_lookup → 抛异常 → ask 保守
        assert meta.decision == "ask"

    def test_reversible_lookup_unknown_action_asks(self):
        """lookup 查不到动作返回 None → ask(保守)。"""
        def _lookup(a: str) -> "bool | None":
            return None  # 未注册动作
        meta = evaluate(
            "some_unknown_tool", {},
            gate_level=ApprovalLevel.CONFIRM,
            config=_empty_config(),
            reversible_lookup=_lookup,
        )
        assert meta.decision == "ask"

    def test_l2_hard_deny_not_affected(self):
        """L2 下 hard rule deny 不被 reversible_lookup 降级为 approve。"""
        def _lookup(a: str) -> "bool | None":
            return True  # 声明可逆
        meta = evaluate(
            "run_command", {"cmd": "rm -rf /"},
            gate_level=ApprovalLevel.CONFIRM,
            config=_empty_config(),
            reversible_lookup=_lookup,
        )
        # hard rule 命中后立即 return,不走 _apply_trust_semantics
        assert meta.decision == "deny"
        assert meta.trigger.startswith("hard_rule:")

    def test_no_reversible_lookup_no_change(self):
        """reversible_lookup=None(默认)时行为与 L1 相同。"""
        meta = evaluate(
            "read_file", {},
            gate_level=ApprovalLevel.CONFIRM,
            config=_empty_config(),
            reversible_lookup=None,
        )
        # CONFIRM 档无软规则 → default ask
        assert meta.decision == "ask"


# ────────────────────────────────────────────────────────────────────
# D. gate 层 — L2 透传
# ────────────────────────────────────────────────────────────────────

class TestGateL2Wiring:
    """gate 设 L2 + 注入 reversible_lookup 后真生效。"""

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
        """L2 档位 + reversible=True → _evaluate 决策 approve。"""
        gate = self._gate_l2(True)
        meta = gate._evaluate("read_file", {"path": "x.txt"})
        assert meta is not None
        assert meta.decision == "approve"
        assert meta.trigger == "trust:L2 可逆放行"

    def test_l2_reversible_false_asks(self):
        """L2 档位 + reversible=False → _evaluate 决策 ask。"""
        gate = self._gate_l2(False)
        meta = gate._evaluate("write_file", {"path": "x.txt"})
        assert meta is not None
        assert meta.decision == "ask"

    def test_l2_reversible_none_asks(self):
        """L2 档位 + reversible=None → _evaluate 决策 ask(保守)。"""
        gate = self._gate_l2(None)
        meta = gate._evaluate("mcp_call", {})
        assert meta is not None
        assert meta.decision == "ask"

    def test_l2_no_lookup_injected_asks(self):
        """L2 档位但未注入 reversible_lookup → 保守 ask（退化）。"""
        gate = ApprovalGate()
        gate.set_trust_level(TrustLevel.L2_IRREVERSIBLE_ONLY)
        # 不调用 set_reversible_lookup → _reversible_lookup=None
        meta = gate._evaluate("read_file", {"path": "x.txt"})
        assert meta is not None
        assert meta.decision == "ask"

    def test_l2_audit_trigger_label(self):
        """L2 可逆放行的 trigger 包含 'L2' 字样(供 AuditLog 标记)。"""
        gate = self._gate_l2(True)
        meta = gate._evaluate("read_file", {})
        assert meta is not None
        assert "L2" in meta.trigger


# ────────────────────────────────────────────────────────────────────
# E. L2 — hard rule 不被降级（独立回归）
# ────────────────────────────────────────────────────────────────────

class TestL2HardRuleImmune:
    """L2 任何档位 HARD RULES 不被 reversible_lookup=True 降级。"""

    @pytest.mark.parametrize("cmd,action", [
        ("rm -rf /", "run_command"),
    ])
    def test_hard_rule_deny_survives_l2(self, cmd: str, action: str):
        gate = ApprovalGate()
        gate.set_trust_level(TrustLevel.L2_IRREVERSIBLE_ONLY)
        gate.set_reversible_lookup(lambda _: True)   # 声明"可逆"
        meta = gate._evaluate(action, {"cmd": cmd})
        assert meta is not None
        # hard rule 命中 deny，不被 L2 可逆放行
        assert meta.decision == "deny"


# ────────────────────────────────────────────────────────────────────
# F. L4 行为零变更
# ────────────────────────────────────────────────────────────────────

class TestL4Unchanged:
    """L4 设 trust_level 后：ask_readonly=False，_reversible_check=False。"""

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
# G. /trust status 注解不含"接线中"
# ────────────────────────────────────────────────────────────────────

class TestTrustStatusAnnotation:
    """/trust status 对 L0/L2 不再显示"接线中"。"""

    def test_app_py_no_wiring_annotation(self):
        """tui/app.py 不再含接线中字样。"""
        from pathlib import Path
        src = Path(__file__).parents[2] / "argos_agent" / "tui" / "app.py"
        text = src.read_text(encoding="utf-8")
        assert "接线中" not in text, "tui/app.py 仍含接线中注解，应已摘除"

    def test_trust_dial_no_wiring_annotation(self):
        """trust_dial.py 不再含"P2 未完成前退化 L1"。"""
        from pathlib import Path
        src = Path(__file__).parents[2] / "argos_agent" / "permissions" / "trust_dial.py"
        text = src.read_text(encoding="utf-8")
        assert "P2 未完成前退化 L1" not in text

    def test_approval_py_no_wiring_annotation(self):
        """approval.py 不再含"当前 evaluator 路径无此字段"（旧保守存储注释）。"""
        from pathlib import Path
        src = Path(__file__).parents[2] / "argos_agent" / "approval.py"
        text = src.read_text(encoding="utf-8")
        assert "当前 evaluator 路径无此字段" not in text


# ────────────────────────────────────────────────────────────────────
# H. _apply_trust_semantics 单元测试（纯函数，覆盖边界）
# ────────────────────────────────────────────────────────────────────

class TestApplyTrustSemantics:
    """_apply_trust_semantics 各路径单元测试。"""

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
        """L2 下已有 ask 不会被升格为 approve（即便 reversible=True）。"""
        meta = _apply_trust_semantics(
            self._meta("ask", "soft_ask:dangerous"),
            action="run_command", ask_readonly=False, reversible_lookup=lambda _: True
        )
        # L2 只能把 approve→approve(可逆放行);ask 维持
        assert meta.decision == "ask"

    def test_no_flags_passthrough(self):
        """无 L0/L2 标志时原结果完全透传。"""
        orig = self._meta("approve", "soft_allow:x")
        meta = _apply_trust_semantics(
            orig, action="read_file", ask_readonly=False, reversible_lookup=None
        )
        assert meta is orig
