"""Internal documentation."""
from __future__ import annotations

import pytest

from argos.core.types import Verdict
from argos.permissions.autonomy import (
    AutonomyPolicy, Zone, classify, on_unverifiable_completion,
)
from argos.permissions.config import PermissionsConfig


def _auto_read_file_config() -> PermissionsConfig:
    """Internal documentation."""
    return PermissionsConfig(version=1, tools={"read_file": "auto"})


def test_green_action_does_not_trigger_approval():
    """Internal documentation."""
    config = _auto_read_file_config()
    policy = AutonomyPolicy()
    zone, reason = classify(
        action="read_file",
        args={"path": "src/x.py"},
        reversible=True,
        verdict=Verdict.passed(detail="ok", verify_cmd="pytest -q", attempts=1),
        config=config,
        policy=policy,
    )
    assert zone == Zone.GREEN
    assert "approval" not in reason.lower()


def test_hard_rule_shell_rm_rf_root_classifies_red():
    """Internal documentation."""
    config = PermissionsConfig.empty()
    policy = AutonomyPolicy()
    zone, reason = classify(
        action="run_command",
        args={"command": "rm -rf /"},
        reversible=True,
        verdict=None,
        config=config,
        policy=policy,
    )
    assert zone == Zone.RED, f"rm -rf / 必须 RED,实得 {zone}"
    assert "rm_rf_root" in reason or "hard" in reason.lower()


def test_hard_rule_path_write_classifies_red():
    """Internal documentation."""
    config = PermissionsConfig.empty()
    policy = AutonomyPolicy()
    zone, reason = classify(
        action="write_file",
        args={"path": "/etc/passwd", "content": "x"},
        reversible=True,
        verdict=None,
        config=config,
        policy=policy,
    )
    assert zone == Zone.RED
    assert "system" in reason.lower() or "hard" in reason.lower()


def test_irreversible_action_classifies_red():
    """Internal documentation."""
    config = _auto_read_file_config()
    policy = AutonomyPolicy()
    zone, _ = classify(
        action="read_file",
        args={"path": "src/x.py"},
        reversible=False,
        verdict=Verdict.passed(detail="ok", verify_cmd="pytest -q", attempts=1),
        config=config,
        policy=policy,
    )
    assert zone == Zone.RED


def test_unverifiable_completion_upgrades_to_red():
    """Internal documentation."""
    policy = AutonomyPolicy()
    zone, reason = on_unverifiable_completion(
        verify_cmd="pytest -q",
        verdict=Verdict.unverifiable(detail="tampered", tampered=["tests/test_x.py"], attempts=1),
        policy=policy,
    )
    assert zone == Zone.RED
    assert "unverifiable" in reason.lower() or "tamper" in reason.lower() or "verify" in reason.lower()


def test_unverifiable_with_no_verify_cmd_does_not_upgrade():
    """Internal documentation."""
    policy = AutonomyPolicy()
    result = on_unverifiable_completion(
        verify_cmd=None,
        verdict=Verdict.unverifiable(detail="(no verify_cmd)", tampered=[], attempts=1),
        policy=policy,
    )
    assert result is None, "verify_cmd=None 不该升级 RED(走 NO_TEST 路径)"


def test_passed_verdict_is_green():
    """Internal documentation."""
    config = _auto_read_file_config()
    policy = AutonomyPolicy()
    zone, _ = classify(
        action="read_file",
        args={"path": "src/x.py"},
        reversible=True,
        verdict=Verdict.passed(detail="ok", verify_cmd="pytest -q", attempts=1),
        config=config,
        policy=policy,
    )
    assert zone == Zone.GREEN


def test_failed_verdict_classifies_red():
    """Internal documentation."""
    config = _auto_read_file_config()
    policy = AutonomyPolicy()
    zone, _ = classify(
        action="read_file",
        args={"path": "src/x.py"},
        reversible=True,
        verdict=Verdict.failed(detail="tests failed", verify_cmd="pytest -q", attempts=1),
        config=config,
        policy=policy,
    )
    assert zone == Zone.RED


def test_preauth_downgrades_soft_ask_to_green():
    """Internal documentation."""
    from argos.permissions.config import RuleEntry
    config = PermissionsConfig(
        version=1,
        ask=(RuleEntry(tool="run_command", matcher="git push"),),
    )
    policy = AutonomyPolicy(preauth={"soft_ask:git push": True})
    zone, reason = classify(
        action="run_command",
        args={"command": "git push origin main"},
        reversible=True,
        verdict=Verdict.passed(detail="ok", verify_cmd="pytest -q", attempts=1),
        config=config,
        policy=policy,
    )
    assert zone == Zone.GREEN, f"预授权应把 soft_ask:git push 降到 GREEN,实得 {zone}/{reason}"


def test_preauth_does_NOT_downgrade_hard_rule():
    """Internal documentation."""
    config = PermissionsConfig.empty()
    policy = AutonomyPolicy(preauth={"hard_rule:rm_rf_root": True})
    zone, _ = classify(
        action="run_command",
        args={"command": "rm -rf /"},
        reversible=False,
        verdict=None,
        config=config,
        policy=policy,
    )
    assert zone == Zone.RED, "硬规则不可被预授权降级(铁律)"


def test_preauth_does_NOT_downgrade_irreversible():
    """Internal documentation."""
    config = _auto_read_file_config()
    policy = AutonomyPolicy(preauth={"tool_level:read_file=auto": True})
    zone, _ = classify(
        action="read_file",
        args={"path": "src/x.py"},
        reversible=False,
        verdict=Verdict.passed(detail="ok", verify_cmd="pytest -q", attempts=1),
        config=config,
        policy=policy,
    )
    assert zone == Zone.RED, "不可撤销不可被预授权降级"


def test_slow_action_classifies_yellow():
    """Internal documentation."""
    config = _auto_read_file_config()
    policy = AutonomyPolicy()
    zone, reason = classify(
        action="read_file",
        args={"path": "src/x.py"},
        reversible=True,
        verdict=None,
        config=config,
        policy=policy,
        slow_action=True,
    )
    assert zone == Zone.YELLOW
    assert "slow" in reason.lower() or "clarif" in reason.lower() or "plan" in reason.lower()


def test_vague_goal_classifies_yellow():
    """Internal documentation."""
    config = _auto_read_file_config()
    policy = AutonomyPolicy()
    zone, _ = classify(
        action="read_file",
        args={"path": "src/x.py"},
        reversible=True,
        verdict=None,
        config=config,
        policy=policy,
        goal_vague=True,
    )
    assert zone == Zone.YELLOW


def test_zone_enum_members():
    assert {z.name for z in Zone} == {"GREEN", "YELLOW", "RED"}


def test_policy_defaults_are_safe():
    """Internal documentation."""
    p = AutonomyPolicy()
    assert p.clarification_required is True
    assert p.preauth == {} or len(p.preauth) == 0
    assert "test" in p.slow_actions or len(p.slow_actions) > 0
