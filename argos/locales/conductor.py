"""conductor/* 用户可见文案 (Wave 3).

key 命名空间: cond.*
ZH 值 = 重构前的原始串 verbatim (一字不差)。
EN 值 = 语义对等的自然英文。
"""
from __future__ import annotations

EN: dict[str, str] = {
    # ── conductor/cronlite.py ────────────────────────────────────────────────

    # _parse_field — field labels used in error messages
    "cond.field_minute": "minute",
    "cond.field_hour": "hour",
    "cond.field_mday": "day",
    "cond.field_month": "month",
    "cond.field_wday": "weekday",

    # _parse_field errors
    "cond.cronlite.field_invalid": (
        "cron field {label!r} has invalid value {token!r} (supported: * / */N / integer)"
    ),
    "cond.cronlite.field_out_of_range": (
        "cron field {label!r} value {n} is out of range [{lo}, {hi}]"
    ),
    "cond.cronlite.field_step_lt1": (
        "cron field {label!r} step {step} must be >= 1"
    ),

    # _parse_five_field
    "cond.cronlite.five_field_count": (
        "five-field cron requires exactly 5 fields; got {count}: {spec!r}"
    ),

    # _next_cron_v2
    "cond.cronlite.no_trigger_in_year": (
        "cron expression has no trigger point within 1 year; please check field combination"
    ),

    # next_due — HH:MM branch
    "cond.cronlite.hhmm_out_of_range": (
        "HH:MM time {spec!r} is out of range (HH 0-23, MM 0-59)"
    ),

    # next_due — every branch
    "cond.cronlite.every_n_lt1": (
        "every interval N must be >= 1; got {n!r}"
    ),

    # ── conductor/proposals.py ───────────────────────────────────────────────

    # ProactiveSuggestion.__post_init__
    "cond.proposal.requires_confirmation_true": (
        "ProactiveSuggestion.requires_confirmation must be True "
        "(suggestions always require user confirmation and are never executed automatically)"
    ),
    "cond.proposal.action_invalid": (
        "ProactiveSuggestion.action must be 'run' or 'dream'; got {action!r}"
    ),

    # propose() — reason_human strings
    "cond.proposal.reason_schedule": "Scheduled trigger ({schedule}): {utterance}",
    "cond.proposal.reason_file": "File-change trigger ({path}): {utterance}",

    # ── conductor/orders.py ──────────────────────────────────────────────────

    # StandingOrder.__post_init__
    "cond.order.schedule_required": (
        "StandingOrder kind=schedule must provide schedule field (id={id!r})"
    ),
    "cond.order.trigger_glob_required": (
        "StandingOrder kind=file_trigger must provide trigger_glob field (id={id!r})"
    ),
    "cond.order.action_invalid": (
        "StandingOrder.action must be 'run' or 'dream'; got {action!r} (id={id!r})"
    ),
}

ZH: dict[str, str] = {
    # ── conductor/cronlite.py ────────────────────────────────────────────────

    "cond.field_minute": "分",
    "cond.field_hour": "时",
    "cond.field_mday": "日",
    "cond.field_month": "月",
    "cond.field_wday": "周",

    "cond.cronlite.field_invalid": (
        "cron 字段 {label!r} 非法值 {token!r}（支持 * / */N / 整数）"
    ),
    "cond.cronlite.field_out_of_range": (
        "cron 字段 {label!r} 值 {n} 超出范围 [{lo}, {hi}]"
    ),
    "cond.cronlite.field_step_lt1": (
        "cron 字段 {label!r} 步进 {step} 必须 ≥ 1"
    ),
    "cond.cronlite.five_field_count": (
        "五段 cron 必须有 5 个字段，收到 {count} 个: {spec!r}"
    ),
    "cond.cronlite.no_trigger_in_year": (
        "cron 表达式在 1 年内无触发点，请检查字段组合"
    ),
    "cond.cronlite.hhmm_out_of_range": (
        "HH:MM 时间 {spec!r} 超出范围（HH 0-23，MM 0-59）"
    ),
    "cond.cronlite.every_n_lt1": (
        "every 间隔 N 必须 ≥ 1，收到 {n!r}"
    ),

    # ── conductor/proposals.py ───────────────────────────────────────────────

    "cond.proposal.requires_confirmation_true": (
        "ProactiveSuggestion.requires_confirmation 必须为 True "
        "（建议永远要用户确认，绝不自动执行）"
    ),
    "cond.proposal.action_invalid": (
        "ProactiveSuggestion.action 必须是 'run' 或 'dream'，收到 {action!r}"
    ),
    "cond.proposal.reason_schedule": "定时触发（{schedule}）：{utterance}",
    "cond.proposal.reason_file": "文件变化触发（{path}）：{utterance}",

    # ── conductor/orders.py ──────────────────────────────────────────────────

    "cond.order.schedule_required": (
        "StandingOrder kind=schedule 必须提供 schedule 字段 (id={id!r})"
    ),
    "cond.order.trigger_glob_required": (
        "StandingOrder kind=file_trigger 必须提供 trigger_glob 字段 (id={id!r})"
    ),
    "cond.order.action_invalid": (
        "StandingOrder.action 必须是 'run' 或 'dream'，收到 {action!r} (id={id!r})"
    ),
}
