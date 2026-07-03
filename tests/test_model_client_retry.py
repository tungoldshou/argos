from __future__ import annotations

import asyncio
import json

import httpx
import pytest

from argos.core.models import CredentialPool, ModelClient, ModelTier


def _sse_text(text: str) -> str:
    data = {"type": "content_block_delta", "delta": {"type": "text_delta", "text": text}}
    return (
        f"data: {json.dumps(data)}\n\n"
        'data: {"type":"message_stop"}\n'
    )


def _ok_response(text: str = "ok") -> httpx.Response:
    return httpx.Response(
        200, text=_sse_text(text), headers={"content-type": "text/event-stream"},
    )


def _err_response(status: int, body: str, *, retry_after: str | None = None) -> httpx.Response:
    headers = {"content-type": "application/json"}
    if retry_after is not None:
        headers["retry-after"] = retry_after
    return httpx.Response(status, text=body, headers=headers)


@pytest.mark.asyncio
async def test_stream_429_then_200_rotates_and_succeeds(monkeypatch):
    tier = ModelTier(name="worker", model="m", base_url="https://api.x/anthropic", max_tokens=4096)
    pool = CredentialPool(["key-a", "key-b"])
    call_count = {"n": 0}
    keys_seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        call_count["n"] += 1
        keys_seen.append(request.headers.get("x-api-key", ""))
        if call_count["n"] == 1:
            return _err_response(429, '{"error":"rate limit"}', retry_after="0")
        return _ok_response("成功")

    from argos.core import recovery
    monkeypatch.setattr(recovery, "jittered_backoff", lambda attempt, **kw: 0.0)

    client = ModelClient(tier=tier, pool=pool, transport=httpx.MockTransport(handler))
    chunks = [c async for c in client.stream([{"role": "user", "content": "hi"}], system="S")]

    assert "".join(chunks) == "成功", (
        f"429 后应换 key 重试到成功,实际 chunks={chunks}, keys_seen={keys_seen}"
    )
    assert call_count["n"] == 2, f"应调用 handler 2 次(1×429 + 1×200),实际 {call_count['n']}"
    assert keys_seen[1] != keys_seen[0], (
        f"两次请求应使用不同 key(retry 换了),实际 keys_seen={keys_seen}"
    )


@pytest.mark.asyncio
async def test_stream_401_terminal_marks_terminal_and_raises(monkeypatch):
    tier = ModelTier(name="worker", model="m", base_url="https://api.x/anthropic", max_tokens=4096)
    pool = CredentialPool(["key-bad"])
    call_count = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        call_count["n"] += 1
        return _err_response(401, '{"error":{"type":"authentication_error"}}')

    client = ModelClient(tier=tier, pool=pool, transport=httpx.MockTransport(handler))
    with pytest.raises((httpx.HTTPStatusError, RuntimeError)) as excinfo:
        async for _ in client.stream([{"role": "user", "content": "hi"}], system="S"):
            pass
    if isinstance(excinfo.value, httpx.HTTPStatusError):
        assert excinfo.value.response.status_code == 401
    assert call_count["n"] == 1, (
        f"terminal 401 不应重试(避免无谓 QPS 浪费),实际调用 {call_count['n']} 次"
    )
    assert "key-bad" not in pool._state, "terminal 401 后 key 应被永久剔除"


@pytest.mark.asyncio
async def test_stream_429_exhausted_key_not_reused_immediately(monkeypatch):
    tier = ModelTier(name="worker", model="m", base_url="https://api.x/anthropic", max_tokens=4096)
    pool = CredentialPool(["key-a", "key-b"])
    keys_seen: list[str] = []
    call_count = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        call_count["n"] += 1
        keys_seen.append(request.headers.get("x-api-key", ""))
        if call_count["n"] == 1:
            return _err_response(429, "rate limit", retry_after="5")
        return _ok_response("ok")

    from argos.core import recovery
    monkeypatch.setattr(recovery, "jittered_backoff", lambda attempt, **kw: 0.0)

    client = ModelClient(tier=tier, pool=pool, transport=httpx.MockTransport(handler))
    _ = [c async for c in client.stream([{"role": "user", "content": "hi"}], system="S")]
    _ = [c async for c in client.stream([{"role": "user", "content": "hi"}], system="S")]
    assert call_count["n"] == 3, f"应共 3 次请求(1×429 + 2×200),实际 {call_count['n']}"
    assert keys_seen[2] != "key-a", (
        f"key-a 在 5s exhausted 期内不应被 least_used 选回,实际 keys_seen={keys_seen}"
    )


@pytest.mark.asyncio
async def test_stream_transport_error_then_200_retries(monkeypatch):
    tier = ModelTier(name="worker", model="m", base_url="https://api.x/anthropic", max_tokens=4096)
    pool = CredentialPool(["key-a"])
    call_count = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        call_count["n"] += 1
        if call_count["n"] == 1:
            raise httpx.RemoteProtocolError("Server disconnected without sending a response.")
        return _ok_response("已恢复")

    from argos.core import recovery
    monkeypatch.setattr(recovery, "jittered_backoff", lambda attempt, **kw: 0.0)

    client = ModelClient(tier=tier, pool=pool, transport=httpx.MockTransport(handler))
    chunks = [c async for c in client.stream([{"role": "user", "content": "hi"}], system="S")]
    assert "".join(chunks) == "已恢复", f"传输断连应退避重试到成功,实际 chunks={chunks}"
    assert call_count["n"] == 2, f"应重试 1 次(1×断连 + 1×200),实际 {call_count['n']}"


@pytest.mark.asyncio
async def test_stream_transport_error_persistent_raises_after_max_attempts(monkeypatch):
    tier = ModelTier(name="worker", model="m", base_url="https://api.x/anthropic", max_tokens=4096)
    pool = CredentialPool(["key-a"])
    call_count = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        call_count["n"] += 1
        raise httpx.RemoteProtocolError("Server disconnected without sending a response.")

    from argos.core import recovery
    monkeypatch.setattr(recovery, "jittered_backoff", lambda attempt, **kw: 0.0)

    client = ModelClient(tier=tier, pool=pool, transport=httpx.MockTransport(handler))
    with pytest.raises(httpx.TransportError):
        async for _ in client.stream([{"role": "user", "content": "hi"}], system="S"):
            pass
    assert call_count["n"] == 3, (
        f"持续传输断连应在 max_attempts(3) 后抛,实际调用 {call_count['n']} 次"
    )


@pytest.mark.asyncio
async def test_stream_429_persistent_raises_after_max_attempts(monkeypatch):
    tier = ModelTier(name="worker", model="m", base_url="https://api.x/anthropic", max_tokens=4096)
    pool = CredentialPool(["key-a"])

    def handler(request: httpx.Request) -> httpx.Response:
        return _err_response(429, "rate limit", retry_after="0")

    from argos.core import recovery
    monkeypatch.setattr(recovery, "jittered_backoff", lambda attempt, **kw: 0.0)

    client = ModelClient(tier=tier, pool=pool, transport=httpx.MockTransport(handler))
    call_count = {"n": 0}

    def counting_handler(request: httpx.Request) -> httpx.Response:
        call_count["n"] += 1
        return handler(request)

    client2 = ModelClient(
        tier=tier, pool=pool, transport=httpx.MockTransport(counting_handler),
    )
    with pytest.raises(httpx.HTTPStatusError) as excinfo:
        async for _ in client2.stream([{"role": "user", "content": "hi"}], system="S"):
            pass
    assert excinfo.value.response.status_code == 429
    assert call_count["n"] == 3, (
        f"持续 429 应在 max_attempts(3) 后抛,实际调用 {call_count['n']} 次"
    )
