from __future__ import annotations

EN: dict[str, str] = {
    # ── evaluator.py: _check_hard_path_write ────────────────────────────────

    "perm2.eval.system_path_deny": "system path {prefix}* is read-only",
    "perm2.eval.hard_shell_deny": "hard rule {rule} matched, auto-deny",

    # ── evaluator.py: computer hard rules ────────────────────────────────────

    "perm2.eval.computer_hard_ask": (
        "Computer-control action matched non-developer-domain hard rule {rule!r} —"
        " this operation requires a human present in Smart Approval."
    ),

    # ── evaluator.py: soft rule reason strings ───────────────────────────────

    "perm2.eval.soft_deny_reason": "soft rule deny matched: {matcher}",
    "perm2.eval.soft_allow_reason": "soft rule allow matched: {matcher}",
    "perm2.eval.soft_ask_reason": "soft rule ask matched: {matcher}",
    "perm2.eval.secret_ask_reason": (
        "Possible secret pattern matched: {name}; confirm before committing."
    ),

    # ── config.py: load() ────────────────────────────────────────────────────

    "perm2.config.bad_version": (
        "permissions.json version must be 2, got {version!r}; edit or remove permissions.json, then run /permissions reload"
    ),
}

ZH: dict[str, str] = {
    # ── evaluator.py: _check_hard_path_write ────────────────────────────────

    "perm2.eval.system_path_deny": "系统路径 {prefix}* 不可写",
    "perm2.eval.hard_shell_deny": "硬规则 {rule} 命中,自动拒",

    # ── evaluator.py: computer hard rules ────────────────────────────────────

    "perm2.eval.computer_hard_ask": (
        "计算机控制动作命中非开发者域硬规则 {rule!r} ——"
        " Smart Approval 下必须人在场确认。"
    ),

    # ── evaluator.py: soft rule reason strings ───────────────────────────────

    "perm2.eval.soft_deny_reason": "软规则 deny 命中: {matcher}",
    "perm2.eval.soft_allow_reason": "软规则 allow 命中: {matcher}",
    "perm2.eval.soft_ask_reason": "软规则 ask 命中: {matcher}",
    "perm2.eval.secret_ask_reason": "命中疑似密钥模式:{name}; 提交前确认。",

    # ── config.py: load() ────────────────────────────────────────────────────

    "perm2.config.bad_version": (
        "permissions.json version 必须 = 2,收到 {version!r};请编辑或删除 permissions.json,然后运行 /permissions reload"
    ),
}
