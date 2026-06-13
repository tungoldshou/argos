"""模型客户端(契约 §7;spec §3.4)。模型不绑定、无 worker/premium 档位:协议/模型由 config.json
的 active profile / 环境变量决定,经 ProtocolAdapter(protocols.py)支持 Anthropic 与 OpenAI 两类端点。
ModelClient 经协议适配器直连端点(httpx),stream() 出 text 增量(剥 thinking)。
不变量(spec §12.2):若用户配了 escalation profile,切换决策只看外部判据(反复 verify 失败),
绝不靠模型自报 confidence —— 该决策在 recovery/harness,ModelClient 本身不做切换判断。"""
from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass
from typing import Any, AsyncIterator

import httpx

from argos_agent.core.protocols import (  # re-export 保旧导入路径
    get_protocol, _coalesce_consecutive_roles,
)
from argos_agent.core.types import ModelTierName


@dataclass(frozen=True, slots=True)
class ModelTier:
    name: ModelTierName
    model: str
    base_url: str
    max_tokens: int  # 可配(spec §3.4:按模型选上限,解锁产出 ×4),不再硬编码 2048
    # 模型上下文窗口上限(Task 10:ActivityPanel"上下文"区按此算占用百分比)。
    # 给默认值(200k)以不破坏既有按 max_tokens 收尾的构造点;config 按模型填真值。
    context_window: int = 200_000
    protocol: str = "anthropic"   # "anthropic" | "openai";默认值保旧构造点/旧 env 回退零破坏
    multimodal: bool = False       # 当前模型是否支持图像输入(spec §5);来自 config/setup 探针


# ── Credential + CredentialPool ──────────────────────────────────────────────

@dataclass(frozen=True, slots=True)
class Credential:
    key: str
    last_used: float
    exhausted_until: float | None  # 限流后的 TTL 到期时间戳;到点自动复活


class CredentialPool:
    """key 轮换(契约 §7;spec §3.4):least_used + exhausted-TTL + terminal vs transient 401。
    内部用可变 dict 持每个 key 的 last_used/exhausted_until;对外只暴露不可变 Credential 快照。"""

    def __init__(self, keys: list[str]) -> None:
        if not keys:
            raise ValueError("CredentialPool 需要至少 1 个 key")
        # key -> {last_used, exhausted_until}
        self._state: dict[str, dict[str, float | None]] = {
            k: {"last_used": 0.0, "exhausted_until": None} for k in keys
        }

    def _snapshot(self, key: str) -> Credential:
        st = self._state[key]
        return Credential(key=key, last_used=float(st["last_used"] or 0.0),
                          exhausted_until=st["exhausted_until"])  # type: ignore[arg-type]

    def least_used(self) -> Credential:
        now = time.time()
        live = {k: st for k, st in self._state.items()}
        avail = [k for k, st in live.items()
                 if st["exhausted_until"] is None or float(st["exhausted_until"]) <= now]
        if avail:
            pick = min(avail, key=lambda k: float(self._state[k]["last_used"] or 0.0))
        else:
            # 全 exhausted → fail-open 取最早 expire 的(上层据 backoff 退避)。
            pick = min(self._state, key=lambda k: float(self._state[k]["exhausted_until"] or 0.0))
        return self._snapshot(pick)

    def mark_used(self, key: str) -> None:
        if key in self._state:
            self._state[key]["last_used"] = time.time()

    def mark_exhausted(self, key: str, ttl_s: float) -> None:
        """transient 限流 → 设 TTL,到点自动复活。"""
        if key in self._state:
            self._state[key]["exhausted_until"] = time.time() + ttl_s

    def mark_terminal(self, key: str) -> None:
        """terminal 401(key 无效)→ 永久剔除。"""
        self._state.pop(key, None)
        if not self._state:
            raise RuntimeError("所有 credential 均已 terminal 剔除,无可用 key")

    @staticmethod
    def is_terminal_401(status: int, body: str) -> bool:
        """区分 terminal(无效 key,永久剔除)vs transient(限流/配额,设 TTL 复活)。
        只有 401 + 认证语义 才是 terminal;429 或带 rate/quota 语义一律 transient。"""
        if status != 401:
            return False
        b = (body or "").lower()
        transient_markers = ("rate_limit", "rate limit", "quota", "overloaded", "too many")
        if any(m in b for m in transient_markers):
            return False
        terminal_markers = ("authentication_error", "invalid x-api-key", "invalid api key",
                            "permission_error", "unauthorized",
                            # OpenAI / OpenRouter 无效 key 措辞(否则 401 被当 transient 死重试)
                            "invalid_api_key", "incorrect api key", "no auth credentials",
                            "invalid_request_error")
        return any(m in b for m in terminal_markers) or b == ""


# ── ModelClient ───────────────────────────────────────────────────────────────

class ModelClient:
    """协议无关的模型客户端:stream/complete 委托给 Protocol 适配器。
    Anthropic-Messages / OpenAI-Chat-Completions 均走同一代码路径,行为由 tier.protocol 选定。"""

    def __init__(self, *, tier: ModelTier, pool: CredentialPool,
                 transport: httpx.BaseTransport | None = None) -> None:
        self.tier = tier
        self.pool = pool
        self._transport = transport  # 测试注入 MockTransport;生产为 None(真网络)
        self._proto = get_protocol(tier.protocol)   # 按协议选适配器
        # 最近一次 stream 的真实 token 用量(从 SSE 的 message_start/message_delta usage 帧抓)。
        # loop 据此发 CostUpdate 让状态栏 token/计时走起来 —— 真数据,不伪造。
        self.last_usage: dict[str, int] = {"input_tokens": 0, "output_tokens": 0,
                                           "cache_read": 0, "cache_creation": 0}

    def _payload(self, messages: list[dict], system: str,
                 system_dynamic: str | None = None) -> dict[str, Any]:
        # 委托协议(保留方法名:test_payload_normalizes_messages 仍调它)。
        return self._proto.payload(
            messages, system=system, tier=self.tier, system_dynamic=system_dynamic,
        )

    def _capture_usage(self, obj: dict[str, Any]) -> None:
        # 委托协议(保留方法名:test_capture_usage_reads_cache_tokens 仍调它)。
        self._proto.capture_usage(obj, self.last_usage)

    async def stream(self, messages: list[dict], *, system: str,
                     system_dynamic: str | None = None) -> AsyncIterator[str]:
        """每个 attempt 重新选 key + 重新发请求(M3 / agnes-flash 限流真用户必踩)。
        429 / 401-transient → mark_exhausted + 退避 + 重新 least_used + 重试。
        401 + is_terminal_401 → mark_terminal + 抛(同 key 必再 401,无意义重试)。
        5xx → 退避 + 重试(不污染 key)。
        max_attempts=3 后抛最后一次(不撒谎、不死循环、不假装成功)。"""
        from argos_agent.core import recovery  # 局部 import,避免循环 + 测试 monkeypatch 路径稳定
        max_attempts = 3
        for attempt in range(max_attempts):
            cred = self.pool.least_used()
            self.pool.mark_used(cred.key)  # 立即更新 last_used,确保 least_used 轮换(Phase 4 #1)
            # 本次 stream 的 usage 清零;边流边抓 usage 帧。
            self.last_usage = {"input_tokens": 0, "output_tokens": 0,
                               "cache_read": 0, "cache_creation": 0}
            try:
                async for delta in self._stream_one_attempt(
                    cred, messages, system, system_dynamic,
                ):
                    yield delta
                return  # 成功,不再 retry
            except httpx.HTTPStatusError as e:
                status = e.response.status_code
                body = e.response.text or ""
                # 401 + is_terminal_401 → 永久剔除同 key,直接抛(同 key 必再 401,无意义重试;
                # 其它 key 也会 401,只是浪费 QPS)
                if status == 401 and CredentialPool.is_terminal_401(401, body):
                    try:
                        self.pool.mark_terminal(cred.key)
                    except RuntimeError as rexc:
                        # mark_terminal 删完最后 key 主动抛 RuntimeError("无可用 key");
                        # 链回 401 + body 让 probe/UI 仍能看到 status code,而不是只剩空池告警
                        raise RuntimeError(
                            f"HTTP 401 (terminal): {body[:100]} | {rexc}"
                        ) from e
                    raise
                # 5xx → 重试(不 mark_exhausted:服务端问题,污染 key 无用)
                if status in (500, 502, 503, 504):
                    if attempt < max_attempts - 1:
                        await asyncio.sleep(recovery.jittered_backoff(attempt))
                        continue
                    raise
                # 429 / 401-transient → mark_exhausted + 重新 least_used
                if status == 429 or (status == 401
                                      and not CredentialPool.is_terminal_401(401, body)):
                    ttl = self._retry_after_ttl(e.response) or 5.0
                    self.pool.mark_exhausted(cred.key, ttl_s=ttl)
                    if attempt < max_attempts - 1:
                        await asyncio.sleep(recovery.jittered_backoff(attempt))
                        continue
                    raise
                # 其它 4xx(400/403/404)→ 原行为,直接抛(语义性错误,重试无用)
                raise

    async def _stream_one_attempt(
        self, cred: Credential, messages: list[dict], system: str,
        system_dynamic: str | None,
    ) -> AsyncIterator[str]:
        """单次 stream 尝试:2xx → yield deltas;非 2xx → raise_for_status 抛 HTTPStatusError。
        错误响应先把 body aread 满(让 e.response.text 在重试决策时可读)。"""
        headers = self._proto.headers(cred.key)
        url = self._proto.endpoint(self.tier.base_url)
        async with httpx.AsyncClient(transport=self._transport, timeout=300.0) as client:
            async with client.stream("POST", url, headers=headers,
                                     json=self._payload(messages, system, system_dynamic)) as resp:
                if resp.status_code >= 400:
                    # 错误响应 body 较小,先 aread 满,raise_for_status 抛后 e.response.text 可读
                    await resp.aread()
                resp.raise_for_status()
                async for line in resp.aiter_lines():
                    line = line.strip()
                    if not line or not line.startswith("data:"):
                        continue
                    raw = line[len("data:"):].strip()
                    if not raw or raw == "[DONE]":
                        continue
                    try:
                        obj = json.loads(raw)
                    except json.JSONDecodeError:
                        continue
                    self._capture_usage(obj)
                    # 不在 is_done 处提前 break:OpenAI 的 include_usage 把 usage 放在
                    # finish_reason 之后的【单独一帧】(choices:[]),提前 break 会读不到 →
                    # OpenAI 系模型 token/成本恒 0(诚实成本展示被架空)。继续读到流自然结束
                    # (aiter_lines 耗尽 / [DONE]),让尾部 usage-only 帧被 _capture_usage 抓到。
                    # 完成帧及其后的 usage 帧 text_delta 均为空,不会多吐文本。
                    if self._proto.is_done(obj):
                        continue
                    text = self._proto.text_delta(obj)
                    if text:
                        yield text

    def _retry_after_ttl(self, response: httpx.Response) -> float | None:
        """HTTP Retry-After 头(数字秒格式)→ TTL 秒。缺/解析失败 → None(调用方用默认 5s)。"""
        ra = response.headers.get("retry-after")
        if not ra:
            return None
        try:
            return max(0.0, float(ra))
        except ValueError:
            return None

    async def complete(self, messages: list[dict], *, system: str,
                       system_dynamic: str | None = None) -> str:
        parts = [c async for c in self.stream(messages, system=system,
                                              system_dynamic=system_dynamic)]
        return "".join(parts)
