"""permissions/evaluator.py + autonomy.py + config.py + hard_rules.py 用户可见文案 (Wave 3).

key 命名空间: perm2.*
ZH 值 = 重构前的原始串 verbatim (一字不差)。
EN 值 = 语义对等的自然英文；以 "Error:" 开头对应 ZH "错误:" 开头。
"""
from __future__ import annotations

EN: dict[str, str] = {
    # ── evaluator.py: _check_hard_path_write ────────────────────────────────

    "perm2.eval.system_path_deny": "system path {prefix}* is read-only",
    "perm2.eval.hard_shell_deny": "hard rule {rule} matched, auto-deny",

    # ── evaluator.py: computer hard rules ────────────────────────────────────

    "perm2.eval.computer_hard_ask": (
        "Computer-control action matched non-developer-domain hard rule {rule!r} —"
        " this operation requires a human present and cannot be downgraded by any Trust Dial level."
    ),

    # ── evaluator.py: soft rule reason strings ───────────────────────────────

    "perm2.eval.soft_deny_reason": "soft rule deny matched: {matcher}",
    "perm2.eval.soft_allow_reason": "soft rule allow matched: {matcher}",
    "perm2.eval.soft_ask_reason": "soft rule ask matched: {matcher}",

    # ── evaluator.py: cage auto-approve reasons ──────────────────────────────

    "perm2.eval.trusted_accept_edits_cage": "Trusted: accept-edits + in-cage auto-allow",
    "perm2.eval.cautious_cage": (
        "Cautious: in-cage action auto-allowed (only ask at cage wall / dangerous actions)"
    ),
    "perm2.eval.cage_trigger": "trust:cage in-cage auto-allow",

    # ── evaluator.py: _apply_trust_semantics ─────────────────────────────────

    "perm2.eval.l0_trigger": "trust:L0 confirm-every-step",
    "perm2.eval.l0_reason": "L0 level: even read-only actions require confirmation",

    "perm2.eval.l2_approve_trigger": "trust:L2 reversible-auto-allow",
    "perm2.eval.l2_approve_reason": "L2 level: action {action!r} declared reversible, auto-allowed",

    "perm2.eval.l2_ask_trigger": "{trigger}:trust:L2 irreversible/unknown conservative ask",
    "perm2.eval.l2_ask_reason": (
        "L2 level: action {action!r} is irreversible or reversible unknown, conservative confirm"
    ),

    # ── autonomy.py: classify() reason strings ────────────────────────────────

    "perm2.zone.irreversible": "action is irreversible (reversible=False), user confirmation required",
    "perm2.zone.hard_deny": "hard rule triggered: {trigger} — cannot be downgraded",
    "perm2.zone.unverifiable": "verdict=unverifiable: {trigger} — not pretending passed",
    "perm2.zone.failed": "verdict=failed: {trigger} — escalating",
    "perm2.zone.preauth_green": "pre-authorized downgrade: {trigger} → auto",
    "perm2.zone.ask_red": "user approval required: {trigger}",
    "perm2.zone.slow_yellow": "slow/expensive action: {action} — collecting clarification via plan mode at task start",
    "perm2.zone.vague_yellow": "goal is vague — collecting clarification via plan mode at task start",
    "perm2.zone.green": "evaluator approve ({trigger}) + verifiable and reversible",

    # ── autonomy.py: on_unverifiable_completion() ────────────────────────────

    "perm2.zone.unverifiable_completion": (
        "verdict=unverifiable with declared verify_cmd={cmd!r} — {detail} — escalating to human"
    ),

    # ── config.py: PermissionsConfig.__post_init__ ───────────────────────────

    "perm2.config.invalid_default_level": (
        "default_level {level!r} is invalid, must be one of {valid}"
    ),
    "perm2.config.invalid_tool_level": (
        "tool level {level!r} for {tool!r} is invalid, must be one of {valid}"
    ),

    # ── config.py: load() ────────────────────────────────────────────────────

    "perm2.config.bad_version": (
        "permissions.json version must be 1, got {version!r} (v2 reserved for v1.1)"
    ),
    "perm2.config.invalid_default_level_load": (
        "default_level {level!r} is invalid, must be one of {valid}"
    ),
    "perm2.config.tools_not_object": "tools must be an object",
}

ZH: dict[str, str] = {
    # ── evaluator.py: _check_hard_path_write ────────────────────────────────

    "perm2.eval.system_path_deny": "系统路径 {prefix}* 不可写",
    "perm2.eval.hard_shell_deny": "硬规则 {rule} 命中,自动拒",

    # ── evaluator.py: computer hard rules ────────────────────────────────────

    "perm2.eval.computer_hard_ask": (
        "计算机控制动作命中非开发者域硬规则 {rule!r} ——"
        " 此类操作必须人在场确认,Trust Dial 任何档位下均不可降级。"
    ),

    # ── evaluator.py: soft rule reason strings ───────────────────────────────

    "perm2.eval.soft_deny_reason": "软规则 deny 命中: {matcher}",
    "perm2.eval.soft_allow_reason": "软规则 allow 命中: {matcher}",
    "perm2.eval.soft_ask_reason": "软规则 ask 命中: {matcher}",

    # ── evaluator.py: cage auto-approve reasons ──────────────────────────────

    "perm2.eval.trusted_accept_edits_cage": "Trusted:接受编辑+牢笼内放行",
    "perm2.eval.cautious_cage": "Cautious:牢笼内动作自动放行(只在牢笼墙/危险操作问)",
    "perm2.eval.cage_trigger": "trust:cage 牢笼内放行",

    # ── evaluator.py: _apply_trust_semantics ─────────────────────────────────

    "perm2.eval.l0_trigger": "trust:L0 每步确认",
    "perm2.eval.l0_reason": "L0 档位:只读操作也需确认",

    "perm2.eval.l2_approve_trigger": "trust:L2 可逆放行",
    "perm2.eval.l2_approve_reason": "L2 档位:动作 {action!r} 声明为可逆,自动放行",

    "perm2.eval.l2_ask_trigger": "{trigger}:trust:L2 不可逆/未知保守问",
    "perm2.eval.l2_ask_reason": "L2 档位:动作 {action!r} 不可逆或 reversible 未知,保守确认",

    # ── autonomy.py: classify() reason strings ────────────────────────────────

    "perm2.zone.irreversible": "动作不可撤销(reversible=False),需用户确认",
    "perm2.zone.hard_deny": "硬规则触发:{trigger} — 不可降级",
    "perm2.zone.unverifiable": "verdict=unverifiable:{trigger} — 不假装通过",
    "perm2.zone.failed": "verdict=failed:{trigger} — 走升级路径",
    "perm2.zone.preauth_green": "预授权降级:{trigger} → 自动",
    "perm2.zone.ask_red": "需用户审批:{trigger}",
    "perm2.zone.slow_yellow": "慢/贵动作:{action} — 任务开头走 plan mode 收澄清",
    "perm2.zone.vague_yellow": "目标模糊 — 任务开头走 plan mode 收澄清",
    "perm2.zone.green": "evaluator approve ({trigger}) + 可验证可撤销",

    # ── autonomy.py: on_unverifiable_completion() ────────────────────────────

    "perm2.zone.unverifiable_completion": (
        "verdict=unverifiable 且已声明 verify_cmd={cmd!r} — {detail} — 升级问人"
    ),

    # ── config.py: PermissionsConfig.__post_init__ ───────────────────────────

    "perm2.config.invalid_default_level": (
        "default_level {level!r} 非法,需 ∈ {valid}"
    ),
    "perm2.config.invalid_tool_level": (
        "tool level {level!r} for {tool!r} 非法,需 ∈ {valid}"
    ),

    # ── config.py: load() ────────────────────────────────────────────────────

    "perm2.config.bad_version": (
        "permissions.json version 必须 = 1,收到 {version!r}(v2 留 v1.1)"
    ),
    "perm2.config.invalid_default_level_load": (
        "default_level {level!r} 非法,需 ∈ {valid}"
    ),
    "perm2.config.tools_not_object": "tools 必须是 object",
}
