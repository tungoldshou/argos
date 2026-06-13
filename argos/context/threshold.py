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

# 整体压缩(有损一锅端)的阈值下限:绝不在 50% 以下主动整体压 —— 提前压是有损的,
# 会把还要用的细节(报错/文件内容/决定)总结没了,反而加重 context rot(spec 2026-06-07)。
PRECOMPACT_FLOOR: float = 0.5


def safe_compact_threshold(raw: float) -> float:
    """钳制主动整体压缩阈值,防误配成有损提前压。

    · raw <= 0      → 0.0(0 = 关闭主动压,保留既有语义,不强行开启)
    · 0 < raw < 0.5 → 0.5(抬到下限:绝不在 50% 以下整体压)
    · raw >= 0.5    → 原样
    """
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
