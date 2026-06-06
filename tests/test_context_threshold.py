"""#12 Context 可视化:T3 threshold.py 压不压决策(契约 §12;spec §8)。

8 测试覆盖 5 跳过 + 2 允许 + 5% buffer 幂等。"""
from __future__ import annotations

from argos_agent.context.threshold import LastCompactedAt, _should_compact


def test_skip_when_compaction_disabled():
    """compaction_enabled=False → False(spec §8.1 跳过条件 1)。"""
    assert _should_compact(
        used=90_000, window=100_000, threshold=0.8, phase="act",
        compaction_enabled=False,
    ) is False


def test_skip_when_phase_is_verify():
    """phase=verify → False(spec §8.1 跳过条件 2,verify 门禁不破)。"""
    assert _should_compact(
        used=90_000, window=100_000, threshold=0.8, phase="verify",
        compaction_enabled=True,
    ) is False


def test_skip_when_phase_is_plan():
    """phase=plan → False(spec §8.1 跳过条件 2,planner 不破)。"""
    assert _should_compact(
        used=90_000, window=100_000, threshold=0.8, phase="plan",
        compaction_enabled=True,
    ) is False


def test_skip_when_threshold_zero():
    """threshold<=0 → False(spec D17:0 = 不主动压)。"""
    assert _should_compact(
        used=90_000, window=100_000, threshold=0.0, phase="act",
        compaction_enabled=True,
    ) is False


def test_skip_when_ratio_below_threshold():
    """80% 阈值,60% 占用 → False(spec §8.1 跳过条件 4)。"""
    assert _should_compact(
        used=60_000, window=100_000, threshold=0.8, phase="act",
    ) is False


def test_skip_when_just_compacted_5pct_buffer():
    """已压过;used 在 5% buffer 内 → False(spec §8.2 + D9 幂等)。"""
    # already_compacted_at.used=90k, current=91k, window=200k, buffer=10k
    # 91k <= 90k + 10k → False
    assert _should_compact(
        used=91_000, window=200_000, threshold=0.8, phase="act",
        already_compacted_at=LastCompactedAt(used=90_000),
    ) is False


def test_skip_when_recent_verify_failed():
    """last_verdict_fail_count>0 → False(spec §8.1 跳过条件 5,等 verify 收敛)。"""
    assert _should_compact(
        used=90_000, window=100_000, threshold=0.8, phase="act",
        last_verdict_fail_count=1,
    ) is False


def test_allow_when_above_threshold_and_idle():
    """80% 阈值,85% 占用,未压过,无 verify 失败,phase=act → True。"""
    assert _should_compact(
        used=85_000, window=100_000, threshold=0.8, phase="act",
        compaction_enabled=True,
        already_compacted_at=None,
        last_verdict_fail_count=0,
    ) is True


def test_allow_when_above_buffer_after_compact():
    """已压过但 used 已涨过 buffer → True(spec §8.2 又触发)。"""
    # already_compacted_at.used=50k, current=80k, window=100k, buffer=5k
    # 80k > 50k + 5k → True
    assert _should_compact(
        used=80_000, window=100_000, threshold=0.8, phase="act",
        already_compacted_at=LastCompactedAt(used=50_000),
    ) is True


def test_skip_when_window_zero():
    """window<=0 兜底 False(spec §13 不除零)。"""
    assert _should_compact(
        used=0, window=0, threshold=0.8, phase="act",
    ) is False
