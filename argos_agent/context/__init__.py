"""#12 Context 可视化:上下文分桶 + 主动压缩(契约 §12;spec §3)。"""
from argos_agent.context.analyzer import (
    ContextAnalyzer,
    ContextBreakdown,
    ContextBucket,
    analyze,
)
from argos_agent.context.threshold import LastCompactedAt, _should_compact
from argos_agent.context.tokens import token_estimate

__all__ = [
    "ContextAnalyzer",
    "ContextBreakdown",
    "ContextBucket",
    "LastCompactedAt",
    "_should_compact",
    "analyze",
    "token_estimate",
]
