from __future__ import annotations

from argos.context.threshold import LastCompactedAt, _should_compact


def test_skip_when_compaction_disabled():
    assert _should_compact(
        used=90_000, window=100_000, threshold=0.8, phase="act",
        compaction_enabled=False,
    ) is False


def test_skip_when_phase_is_verify():
    assert _should_compact(
        used=90_000, window=100_000, threshold=0.8, phase="verify",
        compaction_enabled=True,
    ) is False


def test_skip_when_phase_is_plan():
    assert _should_compact(
        used=90_000, window=100_000, threshold=0.8, phase="plan",
        compaction_enabled=True,
    ) is False


def test_skip_when_threshold_zero():
    assert _should_compact(
        used=90_000, window=100_000, threshold=0.0, phase="act",
        compaction_enabled=True,
    ) is False


def test_skip_when_ratio_below_threshold():
    assert _should_compact(
        used=60_000, window=100_000, threshold=0.8, phase="act",
    ) is False


def test_skip_when_just_compacted_5pct_buffer():
    # already_compacted_at.used=90k, current=91k, window=200k, buffer=10k
    # 91k <= 90k + 10k → False
    assert _should_compact(
        used=91_000, window=200_000, threshold=0.8, phase="act",
        already_compacted_at=LastCompactedAt(used=90_000),
    ) is False


def test_skip_when_recent_verify_failed():
    assert _should_compact(
        used=90_000, window=100_000, threshold=0.8, phase="act",
        last_verdict_fail_count=1,
    ) is False


def test_allow_when_above_threshold_and_idle():
    assert _should_compact(
        used=85_000, window=100_000, threshold=0.8, phase="act",
        compaction_enabled=True,
        already_compacted_at=None,
        last_verdict_fail_count=0,
    ) is True


def test_allow_when_above_buffer_after_compact():
    # already_compacted_at.used=50k, current=80k, window=100k, buffer=5k
    # 80k > 50k + 5k → True
    assert _should_compact(
        used=80_000, window=100_000, threshold=0.8, phase="act",
        already_compacted_at=LastCompactedAt(used=50_000),
    ) is True


def test_skip_when_window_zero():
    assert _should_compact(
        used=0, window=0, threshold=0.8, phase="act",
    ) is False
