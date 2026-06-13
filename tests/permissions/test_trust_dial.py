"""Trust Dial L0-L4 测试套件。

覆盖点：
- 五档映射表逐项（to_approval_semantics 每档的 approval_level + 关键字段）
- hard_rules_immune 契约：任何档位映射结果 hard_rules_immune 字段为 True
- escalation_warning：升档必非空 / 降档必为空串 / 等档为空
- suggest_escalation：阈值准确 / 返回值永远带警示文案 / L4 不触发 / None 时不返回
- L4 语义里 to_approval_semantics 不含绕过 hard rules 的字段（hard_rules_immune=True）
- EscalationSuggestion.warning 不得为空的契约断言
"""
from __future__ import annotations

import pytest

from argos.permissions.trust_dial import (
    TrustLevel,
    EscalationSuggestion,
    hard_rules_immune,
    escalation_warning,
    suggest_escalation,
    to_approval_semantics,
)


# ─────────────────────────────────────────────────────────────────────────────
# TrustLevel 基础属性
# ─────────────────────────────────────────────────────────────────────────────

class TestTrustLevelBasic:
    """TrustLevel 枚举成员与属性测试。"""

    def test_all_five_levels_exist(self):
        levels = list(TrustLevel)
        assert len(levels) == 5

    def test_integer_order(self):
        """L0 < L1 < L2 < L3 < L4，数值连续单调递增。"""
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
# to_approval_semantics：五档映射表逐项
# ─────────────────────────────────────────────────────────────────────────────

class TestToApprovalSemantics:
    """to_approval_semantics 各档映射正确性测试。"""

    def _sem(self, level: TrustLevel) -> dict:
        sem = to_approval_semantics(level)
        assert isinstance(sem, dict), "必须返回 dict"
        return sem

    # ── L0 ──────────────────────────────────────────────────────────────────

    def test_l0_approval_level_confirm(self):
        sem = self._sem(TrustLevel.L0_EVERY_STEP)
        assert sem["approval_level"] == "confirm"

    def test_l0_ask_readonly_true(self):
        """L0 要连只读操作也问，ask_readonly 必须为 True。"""
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
        """L1 只读操作不问。"""
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
        """L2 依赖 reversible 字段过滤，reversible_check 必须为 True。"""
        sem = self._sem(TrustLevel.L2_IRREVERSIBLE_ONLY)
        assert sem["reversible_check"] is True

    def test_l2_reversible_check_in_description(self):
        """L2 的 description 中应提及 reversible 字段依赖（已接线，无需 P2 依赖标注）。"""
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
        """L4 应标记 TUI 显示红灯。"""
        sem = self._sem(TrustLevel.L4_AUTONOMOUS)
        assert sem.get("show_yolo_indicator") is True

    # ── HARD RULES 不变量（所有档位）───────────────────────────────────────

    @pytest.mark.parametrize("level", list(TrustLevel))
    def test_hard_rules_immune_always_true(self, level: TrustLevel):
        """契约断言：任何档位的 to_approval_semantics 映射结果中
        hard_rules_immune 必须为 True（设计 §6 红线）。"""
        sem = to_approval_semantics(level)
        assert sem["hard_rules_immune"] is True, (
            f"{level} 的 to_approval_semantics 必须含 hard_rules_immune=True"
        )

    @pytest.mark.parametrize("level", list(TrustLevel))
    def test_no_bypass_hard_rules_field(self, level: TrustLevel):
        """映射字典不得含有绕过 hard rules 的字段（skip_hard_rules / bypass_hard_rules 等）。"""
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
# hard_rules_immune 契约函数
# ─────────────────────────────────────────────────────────────────────────────

class TestHardRulesImmune:
    def test_returns_true(self):
        assert hard_rules_immune() is True

    def test_can_assert(self):
        """assert 调用形式不应抛异常。"""
        assert hard_rules_immune()

    def test_always_true_multiple_calls(self):
        """多次调用结果不变。"""
        for _ in range(10):
            assert hard_rules_immune() is True


# ─────────────────────────────────────────────────────────────────────────────
# escalation_warning：升档非空 / 降档空串 / 等档空串
# ─────────────────────────────────────────────────────────────────────────────

class TestEscalationWarning:
    """escalation_warning 各方向测试。"""

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
        """升档必须返回非空警示文案（设计 §6 红线）。"""
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
        """降档（收紧权限）应返回空串，无需警示。"""
        w = escalation_warning(from_l, to_l)
        assert w == "", (
            f"escalation_warning({from_l.name} → {to_l.name}) 降档应为空串，实际: {w!r}"
        )

    @pytest.mark.parametrize("level", list(TrustLevel))
    def test_same_level_returns_empty(self, level: TrustLevel):
        """等档（from == to）应返回空串。"""
        w = escalation_warning(level, level)
        assert w == "", f"等档 escalation_warning({level.name}) 应为空串，实际: {w!r}"

    def test_l4_warning_mentions_hard_rules(self):
        """升到 L4 的警示文案应明确提示 HARD RULES 仍拦截。"""
        w = escalation_warning(TrustLevel.L0_EVERY_STEP, TrustLevel.L4_AUTONOMOUS)
        assert "HARD" in w or "hard" in w.lower() or "硬规" in w, (
            f"升到 L4 的警示应提及 HARD RULES，实际: {w!r}"
        )

    def test_warning_mentions_what_is_relaxed(self):
        """升档警示应说明放宽了什么。"""
        w = escalation_warning(TrustLevel.L0_EVERY_STEP, TrustLevel.L1_DANGEROUS_ONLY)
        # 文案应含有"放宽"或描述了权限变化
        assert len(w) > 20, f"警示文案过短，可能没有实质内容: {w!r}"


# ─────────────────────────────────────────────────────────────────────────────
# suggest_escalation：阈值 / 带警示文案 / 边界条件
# ─────────────────────────────────────────────────────────────────────────────

def _make_history(action: str, approved_count: int, kind: str | None = None) -> list[dict]:
    """辅助：生成 approved_count 次同类操作历史。"""
    entry = {"action": action, "decision": "approved"}
    if kind:
        entry["kind"] = kind
    return [entry] * approved_count


class TestSuggestEscalation:
    """suggest_escalation 测试。"""

    def test_below_threshold_returns_none(self):
        """连续 < 5 次不触发建议。"""
        history = _make_history("write_file", 4)
        result = suggest_escalation(history, current_level=TrustLevel.L0_EVERY_STEP)
        assert result is None

    def test_exactly_threshold_returns_suggestion(self):
        """连续恰好 5 次触发建议。"""
        history = _make_history("write_file", 5)
        result = suggest_escalation(history, current_level=TrustLevel.L0_EVERY_STEP)
        assert result is not None

    def test_above_threshold_returns_suggestion(self):
        """连续 > 5 次也触发建议。"""
        history = _make_history("run_command", 10)
        result = suggest_escalation(history, current_level=TrustLevel.L0_EVERY_STEP)
        assert result is not None

    def test_suggestion_always_has_nonempty_warning(self):
        """建议对象 warning 字段必须非空（设计 §6 红线）。"""
        history = _make_history("write_file", 5)
        result = suggest_escalation(history, current_level=TrustLevel.L0_EVERY_STEP)
        assert result is not None
        assert result.warning, f"EscalationSuggestion.warning 不得为空，实际: {result.warning!r}"

    def test_suggestion_level_not_exceed_l3(self):
        """建议档位不超过 L3（不主动建议 L4 全自治）。"""
        history = _make_history("write_file", 100)
        result = suggest_escalation(history, current_level=TrustLevel.L2_IRREVERSIBLE_ONLY)
        assert result is not None
        assert result.suggested_level <= TrustLevel.L3_SESSION_TRUSTED, (
            f"建议档位不应超过 L3，实际: {result.suggested_level}"
        )

    def test_at_l3_no_suggestion(self):
        """当前已是 L3，不应再建议（不主动推向 L4）。"""
        history = _make_history("write_file", 100)
        result = suggest_escalation(history, current_level=TrustLevel.L3_SESSION_TRUSTED)
        assert result is None, f"L3 不应触发升档建议，实际: {result}"

    def test_at_l4_no_suggestion(self):
        """当前已是 L4，不应触发建议。"""
        history = _make_history("write_file", 100)
        result = suggest_escalation(history, current_level=TrustLevel.L4_AUTONOMOUS)
        assert result is None, f"L4 不应触发升档建议，实际: {result}"

    def test_empty_history_returns_none(self):
        result = suggest_escalation([], current_level=TrustLevel.L0_EVERY_STEP)
        assert result is None

    def test_custom_threshold(self):
        """自定义阈值=3，3 次即触发。"""
        history = _make_history("read_file", 3)
        result = suggest_escalation(
            history, current_level=TrustLevel.L0_EVERY_STEP, threshold=3
        )
        assert result is not None

    def test_custom_threshold_not_reached(self):
        """自定义阈值=3，2 次不触发。"""
        history = _make_history("read_file", 2)
        result = suggest_escalation(
            history, current_level=TrustLevel.L0_EVERY_STEP, threshold=3
        )
        assert result is None

    def test_trigger_count_correct(self):
        """trigger_count 应反映实际连续允许次数。"""
        history = _make_history("write_file", 7)
        result = suggest_escalation(history, current_level=TrustLevel.L0_EVERY_STEP)
        assert result is not None
        assert result.trigger_count == 7

    def test_denied_breaks_consecutive_count(self):
        """被拒绝的操作中断连续计数，连续计数从 0 重新开始。"""
        # 4 次批准 + 1 次拒绝 + 4 次批准 = 最大连续 4，不足 5 次
        history = (
            _make_history("write_file", 4)
            + [{"action": "write_file", "decision": "denied"}]
            + _make_history("write_file", 4)
        )
        result = suggest_escalation(history, current_level=TrustLevel.L0_EVERY_STEP)
        assert result is None, "中断后连续计数重置，不应触发建议"

    def test_different_actions_counted_separately(self):
        """不同类操作分别计数，同类才叠加。"""
        history = (
            _make_history("write_file", 3)
            + _make_history("run_command", 3)
        )
        # 各 3 次，不足 5，不应触发
        result = suggest_escalation(history, current_level=TrustLevel.L0_EVERY_STEP)
        assert result is None

    def test_kind_field_used_for_grouping(self):
        """有 kind 字段时按 kind 分组（而非 action）。"""
        # 不同 action 但同一 kind，共 5 次
        history = [
            {"action": "write_file",  "kind": "file_ops", "decision": "approved"},
            {"action": "edit_file",   "kind": "file_ops", "decision": "approved"},
            {"action": "write_file",  "kind": "file_ops", "decision": "approved"},
            {"action": "delete_file", "kind": "file_ops", "decision": "approved"},
            {"action": "edit_file",   "kind": "file_ops", "decision": "approved"},
        ]
        result = suggest_escalation(history, current_level=TrustLevel.L0_EVERY_STEP)
        assert result is not None, "同 kind 累计 5 次应触发建议"

    def test_suggestion_from_level_matches_current(self):
        """建议的 from_level 应等于传入的 current_level。"""
        history = _make_history("write_file", 5)
        result = suggest_escalation(history, current_level=TrustLevel.L1_DANGEROUS_ONLY)
        assert result is not None
        assert result.from_level is TrustLevel.L1_DANGEROUS_ONLY

    def test_suggestion_contains_reason(self):
        """建议对象的 reason 字段应非空（含触发说明）。"""
        history = _make_history("write_file", 5)
        result = suggest_escalation(history, current_level=TrustLevel.L0_EVERY_STEP)
        assert result is not None
        assert result.reason, "reason 字段不得为空"


# ─────────────────────────────────────────────────────────────────────────────
# EscalationSuggestion 契约断言
# ─────────────────────────────────────────────────────────────────────────────

class TestEscalationSuggestionContract:
    """EscalationSuggestion 自身契约测试。"""

    def test_empty_warning_raises(self):
        """warning 为空串时 __post_init__ 应抛 ValueError。"""
        with pytest.raises(ValueError, match="warning"):
            EscalationSuggestion(
                from_level=TrustLevel.L0_EVERY_STEP,
                suggested_level=TrustLevel.L1_DANGEROUS_ONLY,
                warning="",   # 空串 → 应抛
                reason="test",
                trigger_count=5,
            )

    def test_valid_suggestion_no_error(self):
        """合法的 EscalationSuggestion 不应抛异常。"""
        s = EscalationSuggestion(
            from_level=TrustLevel.L0_EVERY_STEP,
            suggested_level=TrustLevel.L1_DANGEROUS_ONLY,
            warning="⚠ 测试警示",
            reason="测试",
            trigger_count=5,
        )
        assert s.warning == "⚠ 测试警示"

    def test_frozen_immutable(self):
        """EscalationSuggestion 是 frozen dataclass，不可修改。"""
        s = EscalationSuggestion(
            from_level=TrustLevel.L0_EVERY_STEP,
            suggested_level=TrustLevel.L1_DANGEROUS_ONLY,
            warning="⚠ 测试",
            reason="测试",
            trigger_count=5,
        )
        with pytest.raises((AttributeError, TypeError)):
            s.warning = "new"  # type: ignore[misc]
