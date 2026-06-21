"""#25:ModelClient 共享 AsyncClient — 连接池复用(不每步新建 TCP+TLS)。"""
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
    """同一 ModelClient 实例的两次 stream 用同一 _http_client 对象(共享 AsyncClient)。"""
    call_clients: list[int] = []

    tier = _tier()
    pool = CredentialPool(["key-a"])
    client = ModelClient(tier=tier, pool=pool, transport=httpx.MockTransport(lambda r: _sse_ok()))

    # 捕获第一次调用后的 http_client id
    async for _ in client.stream([{"role": "user", "content": "hi"}], system="S"):
        pass
    id1 = id(client._http_client)

    async for _ in client.stream([{"role": "user", "content": "hi2"}], system="S"):
        pass
    id2 = id(client._http_client)

    assert id1 == id2, "同一 ModelClient 两次调用应复用同一 AsyncClient 实例"


@pytest.mark.asyncio
async def test_aclose_clears_client():
    """aclose() 后 _http_client 为 None 或已关闭;再次 stream 会重建。"""
    tier = _tier()
    pool = CredentialPool(["key-a"])
    client = ModelClient(tier=tier, pool=pool, transport=httpx.MockTransport(lambda r: _sse_ok()))

    # 触发第一次建立
    async for _ in client.stream([{"role": "user", "content": "hi"}], system="S"):
        pass
    assert client._http_client is not None

    await client.aclose()
    assert client._http_client is None


@pytest.mark.asyncio
async def test_new_client_after_aclose():
    """aclose 后再 stream 仍能正常工作(新建 AsyncClient)。"""
    tier = _tier()
    pool = CredentialPool(["key-a"])
    client = ModelClient(tier=tier, pool=pool, transport=httpx.MockTransport(lambda r: _sse_ok()))

    async for _ in client.stream([{"role": "user", "content": "hi"}], system="S"):
        pass
    await client.aclose()

    chunks = [c async for c in client.stream([{"role": "user", "content": "hi2"}], system="S")]
    assert "".join(chunks) == "ok"
