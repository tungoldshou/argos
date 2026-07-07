from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass
from typing import Any, AsyncIterator

import httpx

from argos.core.protocols import (
    get_protocol, _coalesce_consecutive_roles,
)
from argos.core.types import ModelTierName
from argos.i18n import t

MODEL_STREAM_NO_VISIBLE_OUTPUT_TIMEOUT_S: float = 120.0


@dataclass(frozen=True, slots=True)
class ModelTier:
    name: ModelTierName
    model: str
    base_url: str
    max_tokens: int
    context_window: int = 200_000
    protocol: str = "anthropic"
    multimodal: bool | None = None


# ── Credential + CredentialPool ──────────────────────────────────────────────

@dataclass(frozen=True, slots=True)
class Credential:
    key: str
    last_used: float
    exhausted_until: float | None


class CredentialPool:

    def __init__(self, keys: list[str]) -> None:
        if not keys:
            raise ValueError(t("core2.models.pool_empty"))
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
            pick = min(self._state, key=lambda k: float(self._state[k]["exhausted_until"] or 0.0))
        return self._snapshot(pick)

    def mark_used(self, key: str) -> None:
        if key in self._state:
            self._state[key]["last_used"] = time.time()

    def mark_exhausted(self, key: str, ttl_s: float) -> None:
        if key in self._state:
            self._state[key]["exhausted_until"] = time.time() + ttl_s

    def mark_terminal(self, key: str) -> None:
        self._state.pop(key, None)
        if not self._state:
            raise RuntimeError(t("core2.models.all_terminal"))

    @staticmethod
    def is_terminal_401(status: int, body: str) -> bool:
        if status != 401:
            return False
        b = (body or "").lower()
        transient_markers = ("rate_limit", "rate limit", "quota", "overloaded", "too many")
        if any(m in b for m in transient_markers):
            return False
        terminal_markers = ("authentication_error", "invalid x-api-key", "invalid api key",
                            "permission_error", "unauthorized",
                            "invalid_api_key", "incorrect api key", "no auth credentials",
                            "invalid_request_error")
        return any(m in b for m in terminal_markers) or b == ""


# ── ModelClient ───────────────────────────────────────────────────────────────

class ModelClient:

    def __init__(self, *, tier: ModelTier, pool: CredentialPool,
                 transport: httpx.BaseTransport | None = None) -> None:
        self.tier = tier
        self.pool = pool
        self._transport = transport
        self._proto = get_protocol(tier.protocol)
        self.last_usage: dict[str, int] = {"input_tokens": 0, "output_tokens": 0,
                                           "cache_read": 0, "cache_creation": 0}
        self._http_client: httpx.AsyncClient | None = None

    def _get_http_client(self) -> httpx.AsyncClient:
        if self._http_client is None or self._http_client.is_closed:
            self._http_client = httpx.AsyncClient(
                transport=self._transport, timeout=300.0,
            )
        return self._http_client

    async def aclose(self) -> None:
        if self._http_client is not None and not self._http_client.is_closed:
            await self._http_client.aclose()
        self._http_client = None

    def _payload(self, messages: list[dict], system: str,
                 system_dynamic: str | None = None) -> dict[str, Any]:
        return self._proto.payload(
            messages, system=system, tier=self.tier, system_dynamic=system_dynamic,
        )

    def _capture_usage(self, obj: dict[str, Any]) -> None:
        self._proto.capture_usage(obj, self.last_usage)

    async def stream(self, messages: list[dict], *, system: str,
                     system_dynamic: str | None = None) -> AsyncIterator[str]:
        from argos.core import recovery
        max_attempts = 3
        for attempt in range(max_attempts):
            cred = self.pool.least_used()
            self.pool.mark_used(cred.key)
            self.last_usage = {"input_tokens": 0, "output_tokens": 0,
                               "cache_read": 0, "cache_creation": 0}
            yielded_any = False
            try:
                async for delta in self._stream_one_attempt(
                    cred, messages, system, system_dynamic,
                ):
                    yielded_any = True
                    yield delta
                return
            except httpx.TransportError:
                if yielded_any or attempt >= max_attempts - 1:
                    raise
                await asyncio.sleep(recovery.jittered_backoff(attempt))
                continue
            except httpx.HTTPStatusError as e:
                status = e.response.status_code
                body = e.response.text or ""
                if status == 401 and CredentialPool.is_terminal_401(401, body):
                    try:
                        self.pool.mark_terminal(cred.key)
                    except RuntimeError as rexc:
                        raise RuntimeError(
                            f"HTTP 401 (terminal): {body[:100]} | {rexc}"
                        ) from e
                    raise
                if status in (500, 502, 503, 504):
                    if attempt < max_attempts - 1:
                        await asyncio.sleep(recovery.jittered_backoff(attempt))
                        continue
                    raise
                if status == 429 or (status == 401
                                      and not CredentialPool.is_terminal_401(401, body)):
                    ttl = self._retry_after_ttl(e.response) or 5.0
                    self.pool.mark_exhausted(cred.key, ttl_s=ttl)
                    if attempt < max_attempts - 1:
                        await asyncio.sleep(recovery.jittered_backoff(attempt))
                        continue
                    raise
                raise

    async def _stream_one_attempt(
        self, cred: Credential, messages: list[dict], system: str,
        system_dynamic: str | None,
    ) -> AsyncIterator[str]:
        headers = self._proto.headers(cred.key)
        url = self._proto.endpoint(self.tier.base_url)
        client = self._get_http_client()
        no_visible_timeout = (
            MODEL_STREAM_NO_VISIBLE_OUTPUT_TIMEOUT_S
            if _messages_have_attachments(messages)
            else None
        )
        stream_cm = client.stream(
            "POST", url, headers=headers,
            json=self._payload(messages, system, system_dynamic),
        )
        resp = None
        try:
            try:
                if no_visible_timeout is None:
                    resp = await stream_cm.__aenter__()
                else:
                    resp = await asyncio.wait_for(
                        stream_cm.__aenter__(), timeout=no_visible_timeout,
                    )
            except asyncio.TimeoutError as e:
                raise TimeoutError(_no_visible_output_message(no_visible_timeout)) from e
            if resp.status_code >= 400:
                await resp.aread()
            resp.raise_for_status()
            saw_visible = False
            line_iter = resp.aiter_lines().__aiter__()
            loop = asyncio.get_running_loop()
            deadline = (
                loop.time() + no_visible_timeout
                if no_visible_timeout is not None
                else None
            )
            while True:
                try:
                    if deadline is None:
                        line = await anext(line_iter)
                    else:
                        remaining = deadline - loop.time()
                        if remaining <= 0:
                            raise TimeoutError(
                                _no_visible_output_message(no_visible_timeout)
                            )
                        line = await asyncio.wait_for(
                            anext(line_iter), timeout=remaining,
                        )
                except StopAsyncIteration:
                    break
                except asyncio.TimeoutError as e:
                    raise TimeoutError(_no_visible_output_message(no_visible_timeout)) from e
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
                    continue
                text = self._proto.text_delta(obj)
                if text:
                    saw_visible = True
                    if no_visible_timeout is not None:
                        deadline = loop.time() + no_visible_timeout
                    yield text
            if no_visible_timeout is not None and not saw_visible:
                raise TimeoutError(_no_visible_output_message(no_visible_timeout))
        finally:
            if resp is not None:
                await stream_cm.__aexit__(None, None, None)

    def _retry_after_ttl(self, response: httpx.Response) -> float | None:
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


def _messages_have_attachments(messages: list[dict]) -> bool:
    return any(bool(m.get("attachments")) for m in messages)


def _no_visible_output_message(timeout_s: float | None) -> str:
    if timeout_s is None:
        return "model stream produced no visible output"
    return f"model stream produced no visible output for {timeout_s:.0f}s while handling image input"
