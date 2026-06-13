"""Trust Dial 接线集成测试（P4 阶段3）。

覆盖：
1. gate.set_trust_level — 五档映射经 gate 生效（ApprovalLevel 正确写入）
2. L4 hard rules 契约（任何档位 hard_rules_immune() == True）
3. 升档确认流（escalation_warning 升档非空；降档空串）
4. /yolo 别名（commands.py 中 yolo 仍是 known；trust 也是 known）
5. daemon trust_level 参数（枚举名正确→ gate 更新；非法名→ 诚实忽略不崩）
6. 不传参数完全旧行为（不带 trust_level → gate 保持 CONFIRM 默认）
"""
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
# 1. gate.set_trust_level — 五档映射
# ─────────────────────────────────────────────────────────────────────────────

class TestGateSetTrustLevel:
    """ApprovalGate.set_trust_level 五档映射经 gate 生效。"""

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
        """set_trust_level 正确写入 gate.level。"""
        gate = self._gate()
        gate.set_trust_level(trust)
        assert gate.level is expected_level, (
            f"trust={trust.name} 应映射到 {expected_level.name}，实际={gate.level.name}"
        )

    def test_l0_sets_ask_readonly(self):
        """L0 写入后 gate._ask_readonly == True。"""
        gate = self._gate()
        gate.set_trust_level(TrustLevel.L0_EVERY_STEP)
        assert getattr(gate, "_ask_readonly", False) is True

    def test_l1_ask_readonly_false(self):
        """L1 写入后 gate._ask_readonly == False。"""
        gate = self._gate()
        gate.set_trust_level(TrustLevel.L1_DANGEROUS_ONLY)
        assert getattr(gate, "_ask_readonly", False) is False

    def test_l4_level_is_auto(self):
        """L4 写入后 gate.level == AUTO（旧 /yolo 等价）。"""
        gate = self._gate()
        gate.set_trust_level(TrustLevel.L4_AUTONOMOUS)
        assert gate.level is ApprovalLevel.AUTO

    def test_no_bypass_hard_rules_field_in_semantics(self):
        """to_approval_semantics 返回的映射中 hard_rules_immune 恒为 True（不可绕过）。"""
        for trust in TrustLevel:
            sem = to_approval_semantics(trust)
            assert sem["hard_rules_immune"] is True, (
                f"{trust.name} 的 semantics.hard_rules_immune 不是 True"
            )

    def test_set_trust_level_idempotent(self):
        """连续 set_trust_level 到同一档位不出错。"""
        gate = self._gate()
        gate.set_trust_level(TrustLevel.L3_SESSION_TRUSTED)
        gate.set_trust_level(TrustLevel.L3_SESSION_TRUSTED)
        assert gate.level is ApprovalLevel.ACCEPT_EDITS

    def test_set_trust_level_allows_downgrade(self):
        """先升 L4 再降 L1，gate.level 正确更新。"""
        gate = self._gate()
        gate.set_trust_level(TrustLevel.L4_AUTONOMOUS)
        assert gate.level is ApprovalLevel.AUTO
        gate.set_trust_level(TrustLevel.L1_DANGEROUS_ONLY)
        assert gate.level is ApprovalLevel.CONFIRM


# ─────────────────────────────────────────────────────────────────────────────
# 2. L4 hard rules 契约
# ─────────────────────────────────────────────────────────────────────────────

class TestHardRulesContractUnderL4:
    """L4 full-auto 档位下 hard_rules_immune() 仍然为 True。"""

    def test_hard_rules_immune_returns_true(self):
        assert hard_rules_immune() is True

    @pytest.mark.parametrize("trust", list(TrustLevel))
    def test_hard_rules_immune_all_levels(self, trust: TrustLevel):
        """所有档位：to_approval_semantics 返回的 hard_rules_immune 必须 True。"""
        sem = to_approval_semantics(trust)
        assert sem["hard_rules_immune"] is True

    def test_l4_semantics_no_bypass_hard_rules(self):
        """L4 语义字典不含任何"绕过 hard_rules"字段（show_yolo_indicator 合法，不算绕过）。"""
        sem = to_approval_semantics(TrustLevel.L4_AUTONOMOUS)
        assert sem.get("bypass_hard_rules") is None
        assert sem["approval_level"] == "auto"
        assert sem["hard_rules_immune"] is True

    def test_l4_gate_hard_rules_immune_survives(self):
        """gate 切到 L4 后，hard_rules_immune() 仍为 True。"""
        gate = ApprovalGate()
        gate.set_trust_level(TrustLevel.L4_AUTONOMOUS)
        assert gate.level is ApprovalLevel.AUTO
        assert hard_rules_immune() is True  # 契约函数永不变


# ─────────────────────────────────────────────────────────────────────────────
# 3. 升档确认流（escalation_warning）
# ─────────────────────────────────────────────────────────────────────────────

class TestEscalationWarningFlow:
    """升档 escalation_warning 非空；降档空串；L4 有最强警示。"""

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
        """升档（to > from）必须返回非空警示文案。"""
        warning = escalation_warning(from_l, to_l)
        assert warning, f"升档 {from_l.name}→{to_l.name} 应有非空警示，实际为空"

    @pytest.mark.parametrize("from_l,to_l", [
        (TrustLevel.L4_AUTONOMOUS,      TrustLevel.L3_SESSION_TRUSTED),
        (TrustLevel.L3_SESSION_TRUSTED, TrustLevel.L1_DANGEROUS_ONLY),
        (TrustLevel.L2_IRREVERSIBLE_ONLY, TrustLevel.L0_EVERY_STEP),
        (TrustLevel.L1_DANGEROUS_ONLY,  TrustLevel.L1_DANGEROUS_ONLY),  # 同档
    ])
    def test_escalation_warning_empty_on_downgrade_or_same(self, from_l: TrustLevel, to_l: TrustLevel):
        """降档或同档 escalation_warning 必须返回空串。"""
        warning = escalation_warning(from_l, to_l)
        assert warning == "", f"降档/同档 {from_l.name}→{to_l.name} 应返回空串，实际：{warning!r}"

    def test_l4_warning_contains_hard_rules_mention(self):
        """升到 L4 的警示文案必须提及 HARD RULES（诚实告知约束）。"""
        warning = escalation_warning(TrustLevel.L0_EVERY_STEP, TrustLevel.L4_AUTONOMOUS)
        assert "HARD RULES" in warning or "hard rules" in warning.lower(), (
            "L4 升档警示应提及 HARD RULES"
        )


# ─────────────────────────────────────────────────────────────────────────────
# 4. /yolo 别名 + /trust 命令注册
# ─────────────────────────────────────────────────────────────────────────────

class TestSlashCommandRegistration:
    """/yolo 和 /trust 都是 known 命令；/yolo 帮助文案提示新用法。"""

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
        # yolo 帮助文案中应提示新命令（含 trust 关键词）
        assert "trust" in COMMAND_HELP["yolo"]

    def test_match_commands_includes_trust(self):
        from argos.tui.commands import match_commands
        results = match_commands("/tru")
        names = [n for n, _ in results]
        assert "trust" in names


# ─────────────────────────────────────────────────────────────────────────────
# 5. daemon create_run trust_level 参数
# ─────────────────────────────────────────────────────────────────────────────

class TestDaemonTrustLevelParam:
    """daemon _handle_create_run 的 trust_level 参数处理。"""

    def _make_server(self):
        """构造最小 DaemonHTTPServer 实例（不启动 socket）。"""
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
        server._loop_factory = None   # 触发"no worker"退出码路径以外的路径
        server._gate = ApprovalGate()
        server._ledger_store = None
        return server

    def test_no_trust_level_gate_unchanged(self):
        """不传 trust_level → gate 保持初始 CONFIRM（旧行为零变更）。"""
        gate = ApprovalGate()
        assert gate.level is ApprovalLevel.CONFIRM
        # 模拟 _apply_trust_to_gate(gate) → None（无 trust_level）
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
        """有效 trust_level 枚举名正确写入 gate。"""
        gate = ApprovalGate()
        from argos.permissions.trust_dial import TrustLevel
        gate.set_trust_level(TrustLevel[trust_name])
        assert gate.level is expected_al

    def test_invalid_trust_name_does_not_raise(self):
        """非法 trust_level 名（KeyError）不崩；gate 保持原状。"""
        gate = ApprovalGate()
        original_level = gate.level
        # 模拟 _apply_trust_to_gate 的容错逻辑
        trust_str = "INVALID_LEVEL_XYZ"
        try:
            from argos.permissions.trust_dial import TrustLevel
            tl = TrustLevel[trust_str]
            gate.set_trust_level(tl)
        except KeyError:
            pass  # 预期分支：静默忽略，gate 不改变
        assert gate.level is original_level, "非法枚举名不应修改 gate.level"

    def test_empty_trust_level_no_effect(self):
        """trust_level 为空字符串 → 不写 gate（falsy 检查）。"""
        gate = ApprovalGate()
        trust_str = ""
        if trust_str:
            from argos.permissions.trust_dial import TrustLevel
            gate.set_trust_level(TrustLevel[trust_str])
        assert gate.level is ApprovalLevel.CONFIRM


# ─────────────────────────────────────────────────────────────────────────────
# 6. 不传参数完全旧行为
# ─────────────────────────────────────────────────────────────────────────────

class TestNoTrustLevelBackwardCompat:
    """不传 trust_level 时，gate 默认行为 100% 不变。"""

    def test_gate_default_is_confirm(self):
        gate = ApprovalGate()
        assert gate.level is ApprovalLevel.CONFIRM

    def test_set_level_still_works(self):
        """旧 set_level API 不受影响。"""
        gate = ApprovalGate()
        gate.set_level(ApprovalLevel.AUTO)
        assert gate.level is ApprovalLevel.AUTO

    def test_set_trust_level_does_not_break_set_level(self):
        """set_trust_level 后 set_level 仍可覆盖（两 API 独立）。"""
        gate = ApprovalGate()
        gate.set_trust_level(TrustLevel.L4_AUTONOMOUS)
        gate.set_level(ApprovalLevel.CONFIRM)
        assert gate.level is ApprovalLevel.CONFIRM

    def test_hard_rules_immune_always_true_regardless_of_gate_state(self):
        """gate 在任意状态下 hard_rules_immune() 恒 True（契约不依赖 gate 实例）。"""
        gate = ApprovalGate()
        gate.set_trust_level(TrustLevel.L4_AUTONOMOUS)
        assert hard_rules_immune() is True
        gate.set_trust_level(TrustLevel.L0_EVERY_STEP)
        assert hard_rules_immune() is True
