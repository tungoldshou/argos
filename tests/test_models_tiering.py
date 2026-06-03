"""模型分档(契约 §7):ModelTier frozen + max_tokens 可配 + ModelClient stream/complete(注入 transport)。"""
import json

import httpx
import pytest

from argos_agent.core.models import ModelTier, ModelClient, CredentialPool


def test_model_tier_frozen_and_fields():
    t = ModelTier(name="worker", model="MiniMax-M2", base_url="https://x/anthropic", max_tokens=4096)
    assert t.name == "worker"
    assert t.max_tokens == 4096
    with pytest.raises(Exception):
        t.max_tokens = 1  # type: ignore[misc]


def _sse_transport(text_pieces: list[str]) -> httpx.MockTransport:
    """造一个吐 Anthropic content_block_delta SSE 的 mock transport。"""
    def handler(request: httpx.Request) -> httpx.Response:
        lines = []
        for piece in text_pieces:
            data = {"type": "content_block_delta", "delta": {"type": "text_delta", "text": piece}}
            lines.append(f"event: content_block_delta\ndata: {json.dumps(data)}\n")
        lines.append('event: message_stop\ndata: {"type":"message_stop"}\n')
        body = "\n".join(lines)
        return httpx.Response(200, text=body, headers={"content-type": "text/event-stream"})
    return httpx.MockTransport(handler)


@pytest.mark.asyncio
async def test_model_client_stream_yields_text_strips_thinking():
    tier = ModelTier(name="worker", model="m", base_url="https://api.x/anthropic", max_tokens=4096)
    pool = CredentialPool(["key-a"])
    client = ModelClient(tier=tier, pool=pool, transport=_sse_transport(["你", "好"]))
    chunks = [c async for c in client.stream([{"role": "user", "content": "hi"}], system="S")]
    assert "".join(chunks) == "你好"


@pytest.mark.asyncio
async def test_model_client_complete_returns_full_text():
    tier = ModelTier(name="worker", model="m", base_url="https://api.x/anthropic", max_tokens=4096)
    pool = CredentialPool(["key-a"])
    client = ModelClient(tier=tier, pool=pool, transport=_sse_transport(["完", "整"]))
    out = await client.complete([{"role": "user", "content": "hi"}], system="S")
    assert out == "完整"


@pytest.mark.asyncio
async def test_stream_rotates_credentials_via_mark_used():
    """#1:ModelClient.stream 调用后 least_used 应能选到不同 key(mark_used 确实执行)。"""
    tier = ModelTier(name="worker", model="m", base_url="https://api.x/anthropic", max_tokens=4096)
    pool = CredentialPool(["key-x", "key-y"])
    keys_used: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        keys_used.append(request.headers.get("x-api-key", ""))
        data = {"type": "content_block_delta", "delta": {"type": "text_delta", "text": "ok"}}
        return httpx.Response(
            200,
            text=f"data: {json.dumps(data)}\n\ndata: {{\"type\":\"message_stop\"}}\n",
            headers={"content-type": "text/event-stream"},
        )

    client = ModelClient(tier=tier, pool=pool, transport=httpx.MockTransport(handler))
    msgs = [{"role": "user", "content": "hi"}]
    # 首次调用
    _ = [c async for c in client.stream(msgs, system="S")]
    # 二次调用
    _ = [c async for c in client.stream(msgs, system="S")]
    # 两次使用的 key 必须不同(mark_used 更新了 last_used → least_used 轮到另一个)
    assert len(keys_used) == 2, "stream 应被调用两次"
    assert keys_used[0] != keys_used[1], (
        f"两次 stream 使用了同一个 key={keys_used[0]!r},mark_used 未正确轮换"
    )


@pytest.mark.asyncio
async def test_model_client_sends_max_tokens_from_tier():
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.content)
        captured["auth"] = request.headers.get("x-api-key")
        data = {"type": "content_block_delta", "delta": {"type": "text_delta", "text": "x"}}
        return httpx.Response(200, text=f"data: {json.dumps(data)}\n\ndata: {{\"type\":\"message_stop\"}}\n",
                              headers={"content-type": "text/event-stream"})

    tier = ModelTier(name="worker", model="m", base_url="https://api.x/anthropic", max_tokens=12345)
    pool = CredentialPool(["key-a"])
    client = ModelClient(tier=tier, pool=pool, transport=httpx.MockTransport(handler))
    _ = [c async for c in client.stream([{"role": "user", "content": "hi"}], system="S")]
    assert captured["body"]["max_tokens"] == 12345
    assert captured["body"]["model"] == "m"
    assert captured["auth"] == "key-a"
