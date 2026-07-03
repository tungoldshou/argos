import pytest

from argos.core.honesty import (
    HONESTY_SYSTEM,
    UNTRUSTED_OPEN,
    UNTRUSTED_CLOSE,
    format_untrusted,
    compose_system,
    StreamingContextScrubber,
)


def test_honesty_system_content_preserved():
    assert "<honesty>" in HONESTY_SYSTEM
    assert "web_search" in HONESTY_SYSTEM
    assert "exit code" in HONESTY_SYSTEM


def test_compose_system_locks_order():
    untrusted = format_untrusted(["[skill] x\nbody"], [])
    composed = compose_system(HONESTY_SYSTEM, untrusted)
    assert composed.index(HONESTY_SYSTEM) < composed.index(UNTRUSTED_OPEN)
    assert UNTRUSTED_OPEN in composed and UNTRUSTED_CLOSE in composed


def test_compose_system_empty_untrusted_no_fence():
    composed = compose_system(HONESTY_SYSTEM, "")
    assert composed == HONESTY_SYSTEM
    assert UNTRUSTED_OPEN not in composed


def test_format_untrusted_empty_returns_blank():
    assert format_untrusted([], []) == ""


def test_scrubber_strips_fence_in_single_chunk():
    s = StreamingContextScrubber()
    out = s.feed(f"答案是 42 {UNTRUSTED_OPEN} 偷偷泄露 {UNTRUSTED_CLOSE} 结束")
    assert UNTRUSTED_OPEN not in out
    assert "偷偷泄露" not in out
    assert "答案是 42" in out
    assert "结束" in out


def test_scrubber_strips_fence_split_across_chunks():
    s = StreamingContextScrubber()
    half = len(UNTRUSTED_OPEN) // 2
    out = ""
    out += s.feed("正常 " + UNTRUSTED_OPEN[:half])
    out += s.feed(UNTRUSTED_OPEN[half:] + " 机密 " + UNTRUSTED_CLOSE + " 尾")
    out += s.flush()
    assert UNTRUSTED_OPEN not in out
    assert "机密" not in out
    assert "正常" in out
    assert "尾" in out


def test_scrubber_passes_clean_text_unchanged():
    s = StreamingContextScrubber()
    out = s.feed("完全干净的文本") + s.flush()
    assert out == "完全干净的文本"


def test_scrubber_holdback_partial_marker_until_flush():
    s = StreamingContextScrubber()
    prefix = UNTRUSTED_OPEN[:3]
    out1 = s.feed("文字" + prefix)
    assert prefix not in out1
    out2 = s.flush()
    assert (out1 + out2) == "文字" + prefix
