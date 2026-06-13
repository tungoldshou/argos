"""恢复(契约 §7;spec §3.3 L4):classify_error 分类 + jittered backoff 单调 + 异常链真因。"""
import httpx
import pytest

from argos.core.recovery import ClassifiedError, classify_error, jittered_backoff


def _http_status_error(status: int, body: str = "") -> httpx.HTTPStatusError:
    req = httpx.Request("POST", "https://api.x/v1/messages")
    resp = httpx.Response(status, text=body, request=req)
    return httpx.HTTPStatusError(f"{status}", request=req, response=resp)


def test_classify_429_rotate_and_retry():
    c = classify_error(_http_status_error(429, "too many requests"))
    assert c.retryable is True
    assert c.should_rotate is True
    assert c.should_compress is False


@pytest.mark.parametrize("status", [500, 502, 503])
def test_classify_5xx_retryable(status):
    c = classify_error(_http_status_error(status, "server error"))
    assert c.retryable is True
    assert c.should_rotate is False


def test_classify_context_overflow_compress():
    # 上下文超限 → should_compress(触发 compaction),retryable
    c = classify_error(ValueError("prompt is too long: 200000 tokens > context_length_exceeded"))
    assert c.should_compress is True
    assert c.retryable is True


def test_classify_terminal_401_not_retryable_but_rotate():
    # terminal 401(无效 key)→ 不可重试同 key,但应 rotate 换 key
    c = classify_error(_http_status_error(401, '{"error":{"type":"authentication_error"}}'))
    assert c.should_rotate is True
    assert c.retryable is False


def test_classify_unknown_not_retryable():
    c = classify_error(RuntimeError("某种未知错误"))
    assert c.retryable is False
    assert c.should_fallback is False


def test_classify_detail_flattens_chain():
    # 异常链真因(spec §3.3 L5 挖 4 层):detail 应含底层原因文本
    try:
        try:
            raise ValueError("底层真因")
        except ValueError as e:
            raise RuntimeError("中间包装") from e
    except RuntimeError as outer:
        c = classify_error(outer)
    assert "底层真因" in c.detail


def test_jittered_backoff_monotonic_with_jitter():
    # 期望随 attempt 增大(基数翻倍),且带抖动(同 attempt 多次不全等)。
    b0 = [jittered_backoff(0) for _ in range(20)]
    b3 = [jittered_backoff(3) for _ in range(20)]
    assert max(b0) < min(b3)            # attempt 越大,下界越高
    assert len(set(b0)) > 1            # 有抖动(不是常数)
    assert all(x >= 0 for x in b0 + b3)
