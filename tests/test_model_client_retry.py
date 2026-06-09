"""模型客户端 retry+rotate(M3 限流真用户必踩):429 轮换 key 退避,401+terminal 永久剔除。
契约: stream 遇 429 → mark_exhausted + sleep + 重新 least_used + 再试;401+is_terminal_401
→ mark_terminal + 立即抛(同 key 必再 401,不浪费 QPS);5xx → 重试同 key。
"""
from __future__ import annotations

import asyncio
import json

import httpx
import pytest

from argos_agent.core.models import CredentialPool, ModelClient, ModelTier


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
    """M3 / agnes-flash 限流场景:第 1 次 429,第 2 次 200 → stream 应轮换到下一个 key 并成功。
    真用户场景:best_of_n 3 个候选并发撞限流,失败者要能 retry 复活(而不是全失败)。"""
    tier = ModelTier(name="worker", model="m", base_url="https://api.x/anthropic", max_tokens=4096)
    pool = CredentialPool(["key-a", "key-b"])
    call_count = {"n": 0}
    keys_seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        call_count["n"] += 1
        keys_seen.append(request.headers.get("x-api-key", ""))
        if call_count["n"] == 1:
            # 第一次撞限流 — Retry-After=0 让测试跑得快
            return _err_response(429, '{"error":"rate limit"}', retry_after="0")
        return _ok_response("成功")

    # 把 jittered_backoff 替成 0,测试不卡
    from argos_agent.core import recovery
    monkeypatch.setattr(recovery, "jittered_backoff", lambda attempt, **kw: 0.0)

    client = ModelClient(tier=tier, pool=pool, transport=httpx.MockTransport(handler))
    chunks = [c async for c in client.stream([{"role": "user", "content": "hi"}], system="S")]

    assert "".join(chunks) == "成功", (
        f"429 后应换 key 重试到成功,实际 chunks={chunks}, keys_seen={keys_seen}"
    )
    assert call_count["n"] == 2, f"应调用 handler 2 次(1×429 + 1×200),实际 {call_count['n']}"
    # 第 1 次 key 被 mark_exhausted → 第 2 次 least_used 选 key-b(若 key-b 存在)。
    # 但用 2 个 key 时第 1 次可能就选 key-a,先看实际表现。
    assert keys_seen[1] != keys_seen[0], (
        f"两次请求应使用不同 key(retry 换了),实际 keys_seen={keys_seen}"
    )


@pytest.mark.asyncio
async def test_stream_401_terminal_marks_terminal_and_raises(monkeypatch):
    """401 + invalid_api_key → mark_terminal(永久剔除),不重试,直接抛。
    不重试原因:同 key 必再 401,其它 key 也会 401(同账号),重试浪费 QPS 而已。"""
    tier = ModelTier(name="worker", model="m", base_url="https://api.x/anthropic", max_tokens=4096)
    pool = CredentialPool(["key-bad"])
    call_count = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        call_count["n"] += 1
        return _err_response(401, '{"error":{"type":"authentication_error"}}')

    client = ModelClient(tier=tier, pool=pool, transport=httpx.MockTransport(handler))
    # mark_terminal 删完最后 key 会主动抛 RuntimeError("所有 credential 均已 terminal 剔除") —
    # 这是更直白的"key 全废,去 `argos setup`"信号,比吞成 401 误导用户重试要好。
    with pytest.raises((httpx.HTTPStatusError, RuntimeError)) as excinfo:
        async for _ in client.stream([{"role": "user", "content": "hi"}], system="S"):
            pass
    if isinstance(excinfo.value, httpx.HTTPStatusError):
        assert excinfo.value.response.status_code == 401
    assert call_count["n"] == 1, (
        f"terminal 401 不应重试(避免无谓 QPS 浪费),实际调用 {call_count['n']} 次"
    )
    # mark_terminal 把 key 从 pool 删了;此时 pool 已空。
    assert "key-bad" not in pool._state, "terminal 401 后 key 应被永久剔除"


@pytest.mark.asyncio
async def test_stream_429_exhausted_key_not_reused_immediately(monkeypatch):
    """429 后 key-a 被 mark_exhausted(ttl=5s) → 立刻再 stream 应选 key-b(轮换有效)。"""
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

    from argos_agent.core import recovery
    monkeypatch.setattr(recovery, "jittered_backoff", lambda attempt, **kw: 0.0)

    client = ModelClient(tier=tier, pool=pool, transport=httpx.MockTransport(handler))
    # 第一次 stream:第 1 次请求 429 → 轮换 → 第 2 次请求 200(key-b)
    _ = [c async for c in client.stream([{"role": "user", "content": "hi"}], system="S")]
    # 第二次 stream:key-a 仍在 exhausted 状态,key-b 被 mark_used 过
    _ = [c async for c in client.stream([{"role": "user", "content": "hi"}], system="S")]
    assert call_count["n"] == 3, f"应共 3 次请求(1×429 + 2×200),实际 {call_count['n']}"
    # keys_seen[0]=key-a (第 1 次 stream 撞限流),keys_seen[1]=key-b (重试成功)
    # keys_seen[2] 应仍是 key-a(exhausted 期间 least_used 选 key-b;但 key-b 也被 mark_used 过;
    # least_used 选 last_used 最小的 = key-a(若已过 exhausted 期)? 不,key-a 还在 5s 期内 → 选 key-b)
    # 修正断言:第二次 stream 不应再选 key-a(还在 exhausted 期)
    assert keys_seen[2] != "key-a", (
        f"key-a 在 5s exhausted 期内不应被 least_used 选回,实际 keys_seen={keys_seen}"
    )


@pytest.mark.asyncio
async def test_stream_429_persistent_raises_after_max_attempts(monkeypatch):
    """持续 429 直到 max attempts → 抛最后一次 429(不无限重试、不撒谎说成 200)。"""
    tier = ModelTier(name="worker", model="m", base_url="https://api.x/anthropic", max_tokens=4096)
    pool = CredentialPool(["key-a"])

    def handler(request: httpx.Request) -> httpx.Response:
        return _err_response(429, "rate limit", retry_after="0")

    from argos_agent.core import recovery
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
    # max_attempts=3 → 调 3 次后抛
    assert call_count["n"] == 3, (
        f"持续 429 应在 max_attempts(3) 后抛,实际调用 {call_count['n']} 次"
    )
