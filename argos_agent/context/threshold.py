"""#12 Context 可视化:压不压决策(契约 §12;spec §8)。

纯函数 _should_compact(...) → bool。短路顺序:
1) compaction_enabled=False → False
2) phase in (verify, plan) → False(spec D4 不破门禁/规划)
3) threshold<=0 → False(spec D17 0=不主动压)
4) window<=0 → False(防除零)
5) used/window < threshold → False
6) last_verdict_fail_count>0 → False(等 verify 收敛)
7) already_compacted_at 且 used <= used_at_compact + 5%*window → False(spec D9 幂等)
8) 默认 → True"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class LastCompactedAt:
    """压前 used 快照,spec §8.2 幂等关键。"""
    used: int


# 5% buffer(spec D9 留余量,防刚压完又涨一点点就再压)。
_BUFFER_RATIO: float = 0.05


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
    """判定要不要压。短路顺序见模块 docstring。"""
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
