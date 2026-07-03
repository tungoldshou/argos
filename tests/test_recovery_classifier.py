"""Internal documentation."""
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
    c = classify_error(ValueError("prompt is too long: 200000 tokens > context_length_exceeded"))
    assert c.should_compress is True
    assert c.retryable is True


def test_classify_terminal_401_not_retryable_but_rotate():
    c = classify_error(_http_status_error(401, '{"error":{"type":"authentication_error"}}'))
    assert c.should_rotate is True
    assert c.retryable is False


def test_classify_unknown_not_retryable():
    c = classify_error(RuntimeError("某种未知错误"))
    assert c.retryable is False
    assert c.should_fallback is False


def test_classify_detail_flattens_chain():
    try:
        try:
            raise ValueError("底层真因")
        except ValueError as e:
            raise RuntimeError("中间包装") from e
    except RuntimeError as outer:
        c = classify_error(outer)
    assert "底层真因" in c.detail


def test_jittered_backoff_monotonic_with_jitter():
    b0 = [jittered_backoff(0) for _ in range(20)]
    b3 = [jittered_backoff(3) for _ in range(20)]
    assert max(b0) < min(b3)
    assert len(set(b0)) > 1
    assert all(x >= 0 for x in b0 + b3)
