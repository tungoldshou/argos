"""模型分档 + 客户端(契约 §7;spec §3.4)。worker=MiniMax 默认,premium=Claude(--premium)。
ModelClient 直连 Anthropic-Messages 兼容端(httpx),stream() 出 text 增量(剥 thinking)。
CredentialPool 在 Task 6 于本文件扩展(此处先给可用占位)。
cascade 不变量(spec §12.2):升级到 premium 只看外部判据,绝不靠模型自报 confidence ——
该决策在 recovery/harness,ModelClient 本身不做升级判断。"""
from __future__ import annotations

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
                            "permission_error", "unauthorized")
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

    def _payload(self, messages: list[dict], system: str) -> dict[str, Any]:
        # 委托协议(保留方法名:test_payload_normalizes_messages 仍调它)。
        return self._proto.payload(messages, system=system, tier=self.tier)

    def _capture_usage(self, obj: dict[str, Any]) -> None:
        # 委托协议(保留方法名:test_capture_usage_reads_cache_tokens 仍调它)。
        self._proto.capture_usage(obj, self.last_usage)

    async def stream(self, messages: list[dict], *, system: str) -> AsyncIterator[str]:
        cred = self.pool.least_used()
        self.pool.mark_used(cred.key)  # 立即更新 last_used,确保 least_used 轮换(Phase 4 #1)
        headers = self._proto.headers(cred.key)
        url = self._proto.endpoint(self.tier.base_url)
        # 本次 stream 的 usage 清零;边流边抓 usage 帧。
        self.last_usage = {"input_tokens": 0, "output_tokens": 0, "cache_read": 0, "cache_creation": 0}
        async with httpx.AsyncClient(transport=self._transport, timeout=300.0) as client:
            async with client.stream("POST", url, headers=headers,
                                     json=self._payload(messages, system)) as resp:
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
                    if self._proto.is_done(obj):
                        break
                    text = self._proto.text_delta(obj)
                    if text:
                        yield text

    async def complete(self, messages: list[dict], *, system: str) -> str:
        parts = [c async for c in self.stream(messages, system=system)]
        return "".join(parts)
