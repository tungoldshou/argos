"""Internal documentation."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class LastCompactedAt:
    """Internal documentation."""
    used: int


_BUFFER_RATIO: float = 0.05

PRECOMPACT_FLOOR: float = 0.5


def safe_compact_threshold(raw: float) -> float:
    """Internal documentation."""
    if raw <= 0:
        return 0.0
    return max(raw, PRECOMPACT_FLOOR)


def _should_compact(
    *,
    used: int,
    window: int,
    threshold: float,
    phase: str,
    compaction_enabled: bool = True,
    already_compacted_at: LastCompactedAt | None = None,
    last_verdict_fail_count: int = 0,
) -> bool:
    """Internal documentation."""
    if not compaction_enabled:
        return False
    if phase in ("verify", "plan"):
        return False
    if threshold <= 0:
        return False
    if window <= 0:
        return False
    if used / window < threshold:
        return False
    if last_verdict_fail_count > 0:
        return False
    if already_compacted_at is not None:
        buffer = int(window * _BUFFER_RATIO)
        if used <= already_compacted_at.used + buffer:
            return False
    return True
