"""Evaluator 评估顺序铁证(spec §2.5, D15 锁)。"""
from __future__ import annotations

import pytest

from argos.approval import ApprovalLevel
from argos.permissions.config import PermissionsConfig, RuleEntry
from argos.permissions.evaluator import (
    DecisionMeta,
    DecisionType,
    evaluate,
)


def _cfg(**kw) -> PermissionsConfig:
    return PermissionsConfig(version=1, **kw)


# ── 1. hard rule 优先于 soft allow(D5 锁铁证) ────────────────────
def test_hard_rule_beats_soft_allow():
    """软 allow `^rm ` + hard rule rm_rf_root → 仍 deny(hard 先,不可绕)。"""
    cfg = _cfg(allow=(RuleEntry(tool="run_command", matcher=r"^rm "),))
    meta = evaluate("run_command", {"cmd": "rm -rf /"}, gate_level=ApprovalLevel.AUTO, config=cfg)
    assert meta.decision == "deny"
    assert meta.trigger == "hard_rule:rm_rf_root"


# ── 2. soft deny 优先于 per-tool level ────────────────────────────
def test_soft_deny_beats_per_tool_auto():
    cfg = _cfg(tools={"run_command": "auto"}, deny=(RuleEntry(tool="run_command", matcher=r"^docker "),))
    meta = evaluate("run_command", {"cmd": "docker run x"}, gate_level=ApprovalLevel.CONFIRM, config=cfg)
    assert meta.decision == "deny"
    assert meta.trigger == "soft_deny:^docker "


# ── 3. soft allow 短路(不查 level,不查 modal) ─────────────────────
def test_soft_allow_short_circuits():
    cfg = _cfg(allow=(RuleEntry(tool="run_command", matcher=r"^ls "),))
    meta = evaluate("run_command", {"cmd": "ls -la"}, gate_level=ApprovalLevel.AUTO, config=cfg)
    assert meta.decision == "approve"
    assert meta.trigger == "soft_allow:^ls "


# ── 4. soft ask 即便 level=auto 仍走 ask ─────────────────────────
def test_soft_ask_overrides_auto():
    cfg = _cfg(ask=(RuleEntry(tool="run_command", matcher=r"^npm publish"),))
    meta = evaluate("run_command", {"cmd": "npm publish"}, gate_level=ApprovalLevel.AUTO, config=cfg)
    assert meta.decision == "ask"
    assert meta.trigger == "soft_ask:^npm publish"


# ── 5. per-tool override > default_level ─────────────────────────
def test_per_tool_beats_default():
    cfg = _cfg(default_level="auto", tools={"run_command": "confirm"})
    meta = evaluate("run_command", {"cmd": "pytest -x"}, gate_level=ApprovalLevel.AUTO, config=cfg)
    assert meta.decision == "ask"
    assert meta.trigger == "tool_level:run_command=confirm"


# ── 6. 无 default_level + 无 per-tool + 无 soft rule → 走 gate.level ─
def test_falls_back_to_gate_level():
    cfg = _cfg()
    meta = evaluate("run_command", {"cmd": "pytest -x"}, gate_level=ApprovalLevel.AUTO, config=cfg)
    assert meta.decision == "approve"
    assert meta.trigger == "level:auto"


def test_falls_back_to_gate_level_confirm():
    cfg = _cfg()
    meta = evaluate("run_command", {"cmd": "pytest -x"}, gate_level=ApprovalLevel.CONFIRM, config=cfg)
    assert meta.decision == "ask"
    assert meta.trigger == "level:confirm"


# ── 7. secret pattern 命中走 ask(D8 锁),即便 soft allow ───────────
def test_secret_beats_soft_allow():
    """soft allow `^/workspace/\\.env$` 命中 + secret 内容 → 仍 ask(不短路)。"""
    cfg = _cfg(allow=(RuleEntry(tool="write_file", matcher=r"^\.env$"),))
    meta = evaluate(
        "write_file",
        {"path": "/workspace/.env", "content": "AKIAIOSFODNN7EXAMPLE"},
        gate_level=ApprovalLevel.AUTO,
        config=cfg,
    )
    assert meta.decision == "ask"
    assert meta.trigger == "secret:AWS access key"
    assert meta.secret_pattern == "AWS access key"


# ── 8. 12 条 hard rule 全 False → 走 soft 评估路径 ──────────────
def test_no_hard_rule_falls_through():
    """ls -la 不命中任何 hard rule → 走 soft → 走 level。"""
    cfg = _cfg(allow=(RuleEntry(tool="run_command", matcher=r"^ls "),))
    meta = evaluate("run_command", {"cmd": "ls -la"}, gate_level=ApprovalLevel.AUTO, config=cfg)
    assert meta.decision == "approve"
    assert meta.trigger == "soft_allow:^ls "


# ── 9. system path write 拒 ──────────────────────────────────────
def test_system_path_write_denied():
    """write_file /etc/passwd → 走 system path check → deny。"""
    cfg = _cfg(allow=(RuleEntry(tool="write_file", matcher=r".*"),))
    meta = evaluate(
        "write_file", {"path": "/etc/passwd", "content": "x"},
        gate_level=ApprovalLevel.AUTO, config=cfg, workspace="/Users/zc/Projects/argos",
    )
    assert meta.decision == "deny"
    assert meta.trigger.startswith("hard_rule:system_path:")


# ── 10. .env.example 走 allow(教学用) ────────────────────────────
def test_env_template_allowed():
    cfg = _cfg()
    meta = evaluate(
        "write_file",
        {"path": "/workspace/.env.example", "content": "EXAMPLE=x"},
        gate_level=ApprovalLevel.AUTO, config=cfg, workspace="/workspace",
    )
    assert meta.decision == "approve"


# ── 11. workspace 外 .env deny ───────────────────────────────────
def test_env_outside_workspace_denied():
    cfg = _cfg(allow=(RuleEntry(tool="write_file", matcher=r".*"),))
    meta = evaluate(
        "write_file",
        {"path": "/etc/.env", "content": "x"},
        gate_level=ApprovalLevel.AUTO, config=cfg, workspace="/workspace",
    )
    assert meta.decision == "deny"
    # /etc/.env 命中 system path(/etc/)
    assert meta.trigger.startswith("hard_rule:system_path:")


# ── 12. workspace 内 .env 显式 allow 命中 → approve(soft 短路) ──
def test_workspace_env_soft_allow_approves():
    """workspace 内 .env + soft allow 命中 + 无 secret 内容 → approve。"""
    cfg = _cfg(allow=(RuleEntry(tool="write_file", matcher=r"^/workspace/\.env$"),))
    meta = evaluate(
        "write_file",
        {"path": "/workspace/.env", "content": "FOO=bar"},
        gate_level=ApprovalLevel.AUTO, config=cfg, workspace="/workspace",
    )
    assert meta.decision == "approve"
    assert meta.trigger == "soft_allow:^/workspace/\\.env$"
