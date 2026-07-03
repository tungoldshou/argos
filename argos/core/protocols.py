"""Internal documentation."""
from __future__ import annotations

from typing import Any, Protocol as _TypingProtocol, runtime_checkable


def _coalesce_consecutive_roles(messages: list[dict]) -> list[dict]:
    """Internal documentation."""
    out: list[dict] = []
    for m in messages:
        role = m.get("role")
        content = m.get("content", "")
        atts = m.get("attachments")  # list[ImageAttachment] | None
        if out and out[-1]["role"] == role:
            out[-1]["content"] = f"{out[-1]['content']}\n{content}"
            if atts:
                existing = out[-1].get("attachments") or []
                out[-1]["attachments"] = existing + list(atts)
        else:
            entry: dict = {"role": role, "content": content}
            if atts:
                entry["attachments"] = list(atts)
            out.append(entry)
    return out


def _anthropic_wire_message(m: dict) -> dict:
    """Internal documentation."""
    atts = m.get("attachments")
    if not atts:
        return {"role": m["role"], "content": m.get("content", "")}
    from argos.input.attachments import to_base64
    blocks: list[dict] = [{"type": "text", "text": m.get("content", "")}]
    for att in atts:
        blocks.append({
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": att.media_type,
                "data": to_base64(att),
            },
        })
    return {"role": m["role"], "content": blocks}


def _openai_wire_message(m: dict) -> dict:
    """Internal documentation."""
    atts = m.get("attachments")
    if not atts:
        return {"role": m["role"], "content": m.get("content", "")}
    from argos.input.attachments import to_base64
    blocks: list[dict] = [{"type": "text", "text": m.get("content", "")}]
    for att in atts:
        b64 = to_base64(att)
        blocks.append({
            "type": "image_url",
            "image_url": {"url": f"data:{att.media_type};base64,{b64}"},
        })
    return {"role": m["role"], "content": blocks}


@runtime_checkable
class Protocol(_TypingProtocol):
    name: str
    def endpoint(self, base_url: str) -> str: ...
    def headers(self, key: str) -> dict[str, str]: ...
    def payload(self, messages: list[dict], *, system: str, tier: Any,
                system_dynamic: str | None = ...) -> dict[str, Any]: ...
    def text_delta(self, sse_obj: dict[str, Any]) -> str: ...
    def capture_usage(self, sse_obj: dict[str, Any], last_usage: dict[str, int]) -> None: ...
    def is_done(self, sse_obj: dict[str, Any]) -> bool: ...


class AnthropicProtocol:
    name = "anthropic"

    def endpoint(self, base_url: str) -> str:
        b = base_url.rstrip("/")
        return b if b.endswith("/v1/messages") else b + "/v1/messages"

    def headers(self, key: str) -> dict[str, str]:
        return {"x-api-key": key, "anthropic-version": "2023-06-01",
                "content-type": "application/json"}

    def payload(self, messages: list[dict], *, system: str, tier: Any,
                system_dynamic: str | None = None) -> dict[str, Any]:
        #
        if system_dynamic:
            system_blocks: list[dict[str, Any]] = [
                {"type": "text", "text": system, "cache_control": {"type": "ephemeral"}},
                {"type": "text", "text": system_dynamic},
            ]
        else:
            system_blocks = [
                {"type": "text", "text": system, "cache_control": {"type": "ephemeral"}},
            ]
        coalesced = _coalesce_consecutive_roles(messages)
        wire_messages = [_anthropic_wire_message(m) for m in coalesced]
        return {
            "model": tier.model,
            "max_tokens": tier.max_tokens,
            "system": system_blocks,
            "messages": wire_messages,
            "stream": True,
        }

    def text_delta(self, obj: dict[str, Any]) -> str:
        if obj.get("type") == "content_block_delta":
            delta = obj.get("delta") or {}
            if delta.get("type") == "text_delta":
                return delta.get("text", "") or ""
        return ""

    def capture_usage(self, obj: dict[str, Any], last_usage: dict[str, int]) -> None:
        t = obj.get("type")
        if t == "message_start":
            u = (obj.get("message") or {}).get("usage") or {}
            last_usage["input_tokens"] = int(u.get("input_tokens") or 0)
            if u.get("output_tokens") is not None:
                last_usage["output_tokens"] = int(u.get("output_tokens") or 0)
            if u.get("cache_read_input_tokens") is not None:
                last_usage["cache_read"] = int(u.get("cache_read_input_tokens") or 0)
            if u.get("cache_creation_input_tokens") is not None:
                last_usage["cache_creation"] = int(u.get("cache_creation_input_tokens") or 0)
            last_usage["context_total"] = (
                int(u.get("input_tokens") or 0)
                + int(u.get("cache_read_input_tokens") or 0)
                + int(u.get("cache_creation_input_tokens") or 0)
            )
        elif t == "message_delta":
            u = obj.get("usage") or {}
            if u.get("input_tokens") is not None:
                last_usage["input_tokens"] = int(u.get("input_tokens") or 0)
            if u.get("output_tokens") is not None:
                last_usage["output_tokens"] = int(u.get("output_tokens") or 0)
            if u.get("cache_read_input_tokens") is not None:
                last_usage["cache_read"] = int(u.get("cache_read_input_tokens") or 0)

    def is_done(self, obj: dict[str, Any]) -> bool:
        return obj.get("type") == "message_stop"


class OpenAIProtocol:
    """Internal documentation."""
    name = "openai"

    def endpoint(self, base_url: str) -> str:
        b = base_url.rstrip("/")
        return b if b.endswith("/chat/completions") else b + "/chat/completions"

    def headers(self, key: str) -> dict[str, str]:
        return {"Authorization": f"Bearer {key}", "content-type": "application/json"}

    def payload(self, messages: list[dict], *, system: str, tier: Any,
                system_dynamic: str | None = None) -> dict[str, Any]:
        if system_dynamic:
            system_content = f"{system}\n\n{system_dynamic}"
        else:
            system_content = system
        coalesced = _coalesce_consecutive_roles(messages)
        wire_msgs: list[dict] = [{"role": "system", "content": system_content}]
        wire_msgs.extend(_openai_wire_message(m) for m in coalesced)
        return {
            "model": tier.model,
            "max_tokens": tier.max_tokens,
            "messages": wire_msgs,
            "stream": True,
            "stream_options": {"include_usage": True},
        }

    def text_delta(self, obj: dict[str, Any]) -> str:
        choices = obj.get("choices") or []
        if not choices:
            return ""
        return (choices[0].get("delta") or {}).get("content") or ""

    def capture_usage(self, obj: dict[str, Any], last_usage: dict[str, int]) -> None:
        u = obj.get("usage") or {}
        if not u:
            return
        if u.get("prompt_tokens") is not None:
            last_usage["input_tokens"] = int(u.get("prompt_tokens") or 0)
            last_usage["context_total"] = int(u.get("prompt_tokens") or 0)
        if u.get("completion_tokens") is not None:
            last_usage["output_tokens"] = int(u.get("completion_tokens") or 0)
        details = u.get("prompt_tokens_details") or {}
        if details.get("cached_tokens") is not None:
            last_usage["cache_read"] = int(details.get("cached_tokens") or 0)

    def is_done(self, obj: dict[str, Any]) -> bool:
        choices = obj.get("choices") or []
        return bool(choices) and choices[0].get("finish_reason") is not None


def get_protocol(name: str) -> AnthropicProtocol | OpenAIProtocol:
    name = (name or "anthropic").lower()
    if name == "openai":
        return OpenAIProtocol()
    return AnthropicProtocol()
