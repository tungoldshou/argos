"""诚实栈(契约 §3 HONESTY 不变量;spec §3.5/§12.1):HONESTY_SYSTEM 搬迁 + 注入顺序 + Scrubber。"""
import pytest

from argos_agent.core.honesty import (
    HONESTY_SYSTEM,
    UNTRUSTED_OPEN,
    UNTRUSTED_CLOSE,
    format_untrusted,
    compose_system,
    StreamingContextScrubber,
)


def test_honesty_system_content_preserved():
    # 搬迁不丢内容:诚实协议三条 + 工具声明仍在。
    assert "诚实协议" in HONESTY_SYSTEM
    assert "web_search" in HONESTY_SYSTEM
    assert "退出码" in HONESTY_SYSTEM


def test_compose_system_locks_order():
    # 安全段(HONESTY)永远在 untrusted 之前(契约 §3 / spec §12.1)。
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
    # 围栏标记被切成两半跨 chunk —— 状态机必须跨 chunk 识别并吞掉。
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
    # chunk 以"可能是围栏开头的前缀"结尾 → 必须 holdback,不能急着外发(否则切半泄露)。
    s = StreamingContextScrubber()
    prefix = UNTRUSTED_OPEN[:3]
    out1 = s.feed("文字" + prefix)
    assert prefix not in out1            # 前缀被 holdback
    out2 = s.flush()                     # 流结束证明它不是围栏 → 补发
    assert (out1 + out2) == "文字" + prefix
