from __future__ import annotations

import asyncio
import json

import httpx
import pytest

from argos.core.models import ModelClient, ModelTier, CredentialPool


def _tier() -> ModelTier:
    return ModelTier(name="test", model="m", base_url="https://api.x/v1", max_tokens=256)


def _sse_ok(text: str = "ok") -> httpx.Response:
    data = json.dumps({"type": "content_block_delta", "delta": {"type": "text_delta", "text": text}})
    return httpx.Response(
        200, text=f"data: {data}\n\ndata: {{\"type\":\"message_stop\"}}\n",
        headers={"content-type": "text/event-stream"},
    )


@pytest.mark.asyncio
async def test_shared_client_reused_across_calls():
    call_clients: list[int] = []

    tier = _tier()
    pool = CredentialPool(["key-a"])
    client = ModelClient(tier=tier, pool=pool, transport=httpx.MockTransport(lambda r: _sse_ok()))

    async for _ in client.stream([{"role": "user", "content": "hi"}], system="S"):
        pass
    id1 = id(client._http_client)

    async for _ in client.stream([{"role": "user", "content": "hi2"}], system="S"):
        pass
    id2 = id(client._http_client)

    assert id1 == id2, "同一 ModelClient 两次调用应复用同一 AsyncClient 实例"


@pytest.mark.asyncio
async def test_aclose_clears_client():
    tier = _tier()
    pool = CredentialPool(["key-a"])
    client = ModelClient(tier=tier, pool=pool, transport=httpx.MockTransport(lambda r: _sse_ok()))

    async for _ in client.stream([{"role": "user", "content": "hi"}], system="S"):
        pass
    assert client._http_client is not None

    await client.aclose()
    assert client._http_client is None


@pytest.mark.asyncio
async def test_new_client_after_aclose():
    tier = _tier()
    pool = CredentialPool(["key-a"])
    client = ModelClient(tier=tier, pool=pool, transport=httpx.MockTransport(lambda r: _sse_ok()))

    async for _ in client.stream([{"role": "user", "content": "hi"}], system="S"):
        pass
    await client.aclose()

    chunks = [c async for c in client.stream([{"role": "user", "content": "hi2"}], system="S")]
    assert "".join(chunks) == "ok"
