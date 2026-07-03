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


def test_hard_rule_beats_soft_allow():
    cfg = _cfg(allow=(RuleEntry(tool="run_command", matcher=r"^rm "),))
    meta = evaluate("run_command", {"cmd": "rm -rf /"}, gate_level=ApprovalLevel.AUTO, config=cfg)
    assert meta.decision == "deny"
    assert meta.trigger == "hard_rule:rm_rf_root"


def test_soft_deny_beats_per_tool_auto():
    cfg = _cfg(tools={"run_command": "auto"}, deny=(RuleEntry(tool="run_command", matcher=r"^docker "),))
    meta = evaluate("run_command", {"cmd": "docker run x"}, gate_level=ApprovalLevel.CONFIRM, config=cfg)
    assert meta.decision == "deny"
    assert meta.trigger == "soft_deny:^docker "


def test_soft_allow_short_circuits():
    cfg = _cfg(allow=(RuleEntry(tool="run_command", matcher=r"^ls "),))
    meta = evaluate("run_command", {"cmd": "ls -la"}, gate_level=ApprovalLevel.AUTO, config=cfg)
    assert meta.decision == "approve"
    assert meta.trigger == "soft_allow:^ls "


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


def test_secret_beats_soft_allow():
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


def test_no_hard_rule_falls_through():
    cfg = _cfg(allow=(RuleEntry(tool="run_command", matcher=r"^ls "),))
    meta = evaluate("run_command", {"cmd": "ls -la"}, gate_level=ApprovalLevel.AUTO, config=cfg)
    assert meta.decision == "approve"
    assert meta.trigger == "soft_allow:^ls "


def test_system_path_write_denied():
    cfg = _cfg(allow=(RuleEntry(tool="write_file", matcher=r".*"),))
    meta = evaluate(
        "write_file", {"path": "/etc/passwd", "content": "x"},
        gate_level=ApprovalLevel.AUTO, config=cfg, workspace="/Users/zc/Projects/argos",
    )
    assert meta.decision == "deny"
    assert meta.trigger.startswith("hard_rule:system_path:")


def test_env_template_allowed():
    cfg = _cfg()
    meta = evaluate(
        "write_file",
        {"path": "/workspace/.env.example", "content": "EXAMPLE=x"},
        gate_level=ApprovalLevel.AUTO, config=cfg, workspace="/workspace",
    )
    assert meta.decision == "approve"


def test_env_outside_workspace_denied():
    cfg = _cfg(allow=(RuleEntry(tool="write_file", matcher=r".*"),))
    meta = evaluate(
        "write_file",
        {"path": "/etc/.env", "content": "x"},
        gate_level=ApprovalLevel.AUTO, config=cfg, workspace="/workspace",
    )
    assert meta.decision == "deny"
    assert meta.trigger.startswith("hard_rule:system_path:")


def test_workspace_env_soft_allow_approves():
    cfg = _cfg(allow=(RuleEntry(tool="write_file", matcher=r"^/workspace/\.env$"),))
    meta = evaluate(
        "write_file",
        {"path": "/workspace/.env", "content": "FOO=bar"},
        gate_level=ApprovalLevel.AUTO, config=cfg, workspace="/workspace",
    )
    assert meta.decision == "approve"
    assert meta.trigger == "soft_allow:^/workspace/\\.env$"
