"""#12 Context 可视化:上下文分桶 + 主动压缩(契约 §12;spec §3)。"""
from argos.context.analyzer import (
    ContextAnalyzer,
    ContextBreakdown,
    ContextBucket,
    analyze,
)
from argos.context.render import format_json, format_table
from argos.context.threshold import LastCompactedAt, _should_compact
from argos.context.tokens import token_estimate

__all__ = [
    "ContextAnalyzer",
    "ContextBreakdown",
    "ContextBucket",
    "LastCompactedAt",
    "_should_compact",
    "analyze",
    "format_json",
    "format_table",
    "token_estimate",
]
