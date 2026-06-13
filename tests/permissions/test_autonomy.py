"""autonomy Zone 分类 + verify 联动 + 预授权(任务:自主程度绑定到 verify)。

约束(铁律):
- 不削弱 verify_gate / hard_rules
- 复用 evaluator 做 RED 判定
- 预授权【不能】降级硬规则 deny
- 关键:verdict=unverifiable 时绝不声称完成(走 RED 升级,或 bounce/escalate)
"""
from __future__ import annotations

import pytest

from argos.core.types import Verdict
from argos.permissions.autonomy import (
    AutonomyPolicy, Zone, classify, on_unverifiable_completion,
)
from argos.permissions.config import PermissionsConfig


def _auto_read_file_config() -> PermissionsConfig:
    """read_file=auto 让 evaluator 返 approve(GREEN 测试需要 evaluator approve 路径)。"""
    return PermissionsConfig(version=1, tools={"read_file": "auto"})


# ── 验收 a: GREEN 动作不触发审批 ─────────────────────────────
def test_green_action_does_not_trigger_approval():
    """可验证 + 可撤销 + evaluator approve → Zone=GREEN(不触发审批)。"""
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


# ── 验收 b: hard_rule 命中→RED→走 ApprovalGate ────────────────
def test_hard_rule_shell_rm_rf_root_classifies_red():
    """rm -rf / 命中 hard_rule rm_rf_root → evaluator 拒 → classify RED。

    用 reversible=True 让 classify 走到 evaluator(否则 irreversible 路径先拦,无法验证硬规则判定)。
    现实里 rm -rf 本就 irreversible,classify 第一个拦就对——两个 RED 路径双保险。
    """
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
    """写 /etc/passwd 命中系统路径 → RED。"""
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


# ── 验收 b (续): 不可撤销动作 → RED ─────────────────────────
def test_irreversible_action_classifies_red():
    """reversible=False → RED(无论 evaluator 怎么说,不可撤销必升级)。

    read_file=auto 让 evaluator 返 approve,verdict=passed —— 证明 irreversible 自身就触发 RED。
    """
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


# ── 验收 c: verify=unverifiable 的完成不 passed(升级 RED) ──────
def test_unverifiable_completion_upgrades_to_red():
    """verdict=unverifiable + 有声明 verify_cmd → on_unverifiable_completion 返 RED。

    关键护城河:声称完成但 verifier 跑出 unverifiable(篡改/超时)→ 升级问人,不 passed。
    """
    policy = AutonomyPolicy()
    zone, reason = on_unverifiable_completion(
        verify_cmd="pytest -q",
        verdict=Verdict.unverifiable(detail="tampered", tampered=["tests/test_x.py"], attempts=1),
        policy=policy,
    )
    assert zone == Zone.RED
    assert "unverifiable" in reason.lower() or "tamper" in reason.lower() or "verify" in reason.lower()


def test_unverifiable_with_no_verify_cmd_does_not_upgrade():
    """边界:verify_cmd is None(没声明命令)→ 走既有的 NO_TEST 路径,【不】升级 RED。"""
    policy = AutonomyPolicy()
    result = on_unverifiable_completion(
        verify_cmd=None,
        verdict=Verdict.unverifiable(detail="(no verify_cmd)", tampered=[], attempts=1),
        policy=policy,
    )
    assert result is None, "verify_cmd=None 不该升级 RED(走 NO_TEST 路径)"


def test_passed_verdict_is_green():
    """verdict=passed + 可逆 → GREEN(verify 闭环 → 自主继续)。"""
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
    """verdict=failed → RED(走 bounce/escalate)。"""
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


# ── 验收 d: 预授权能把某类 RED 降到自动 ──────────────────────
def test_preauth_downgrades_soft_ask_to_green():
    """预授权某个 soft_ask matcher → 该规则触发的 RED 降到 GREEN。"""
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
    """铁律:硬规则 deny 不可被预授权降级(产品护城河,不得削弱 hard_rules)。"""
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
    """reversible=False 不可被预授权降级(语义边界,不是规则层)。"""
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


# ── YELLOW: 可验证但昂贵/慢,或目标模糊 ────────────────────
def test_slow_action_classifies_yellow():
    """slow_actions 集合里的动作(reversible=True)→ YELLOW(走 plan mode 收澄清)。

    read_file=auto 让 evaluator 返 approve(避开 ask 路径),再显式 slow_action=True → YELLOW。
    """
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
    """goal_vague=True → YELLOW(走 plan mode 收澄清)。"""
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


# ── Zone 枚举值稳定 ────────────────────────────────────
def test_zone_enum_members():
    assert {z.name for z in Zone} == {"GREEN", "YELLOW", "RED"}


def test_policy_defaults_are_safe():
    """AutonomyPolicy 默认值:preauth 空、clarification_required=True、slow_actions 非空。"""
    p = AutonomyPolicy()
    assert p.clarification_required is True
    assert p.preauth == {} or len(p.preauth) == 0
    assert "test" in p.slow_actions or len(p.slow_actions) > 0
