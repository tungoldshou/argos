"""协议适配层(spec §5):把"怎么拼请求 / 怎么解析 SSE / 怎么抓 usage"按协议封装,
ModelClient 协议无关。AnthropicProtocol=现有逻辑抽出;OpenAIProtocol=新增(Task 3)。

不在运行时 import models(避免与 models.py 循环):tier 以鸭子类型用(.model/.max_tokens)。"""
from __future__ import annotations

from typing import Any, Protocol as _TypingProtocol, runtime_checkable


def _coalesce_consecutive_roles(messages: list[dict]) -> list[dict]:
    """合并连续同 role 的消息,保证 user/assistant 交替(Anthropic 兼容端要求,否则 400)。
    多轮/压缩会产生连续同 role;在发请求前把相邻同 role content 用换行并起来(I1 修复,已有逻辑)。

    方案 C 扩展(spec §5):带 attachments 边车字段的消息合并时,attachments 列表一并 concat;
    content 仍是字符串 → store/压缩/诚实检查全部不动。
    """
    out: list[dict] = []
    for m in messages:
        role = m.get("role")
        content = m.get("content", "")
        atts = m.get("attachments")  # list[ImageAttachment] | None
        if out and out[-1]["role"] == role:
            out[-1]["content"] = f"{out[-1]['content']}\n{content}"
            # attachments concat:任意一侧有附件就合并
            if atts:
                existing = out[-1].get("attachments") or []
                out[-1]["attachments"] = existing + list(atts)
            # 若当前消息无 attachments,out[-1] 的 attachments 保持原样
        else:
            entry: dict = {"role": role, "content": content}
            if atts:
                entry["attachments"] = list(atts)
            out.append(entry)
    return out


def _anthropic_wire_message(m: dict) -> dict:
    """把内部消息 dict 物化成 Anthropic wire 格式。

    无 attachments → content 保持裸字符串(零回归)。
    有 attachments → content 展开为 [text_block, image_block, ...] list。
    """
    atts = m.get("attachments")
    if not atts:
        return {"role": m["role"], "content": m.get("content", "")}
    from argos_agent.input.attachments import to_base64
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
    """把内部消息 dict 物化成 OpenAI wire 格式。

    无 attachments → content 保持裸字符串(零回归)。
    有 attachments → content 展开为 [text_block, image_url_block, ...] list。
    """
    atts = m.get("attachments")
    if not atts:
        return {"role": m["role"], "content": m.get("content", "")}
    from argos_agent.input.attachments import to_base64
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
        # 幂等:用户已粘贴完整 .../v1/messages 时不重复追加(防双拼)。
        b = base_url.rstrip("/")
        return b if b.endswith("/v1/messages") else b + "/v1/messages"

    def headers(self, key: str) -> dict[str, str]:
        return {"x-api-key": key, "anthropic-version": "2023-06-01",
                "content-type": "application/json"}

    def payload(self, messages: list[dict], *, system: str, tier: Any,
                system_dynamic: str | None = None) -> dict[str, Any]:
        # prompt caching(显式 opt-in):system 作带 cache_control 的内容块。系统提示是最大、
        # 最稳、且每个 CodeAct 步都原样重发的前缀 → 缓存它,同一 run 内第二步起全命中,
        # 这才是多步 run 真正的省钱点(对齐"让便宜模型可及")。低于端点最小可缓存长度时
        # Anthropic 静默忽略 cache_control(无害);不支持的兼容代理至多忽略该字段。
        #
        # 拆分语义(任务:并行子 agent 共用稳定前缀):当 caller 把"稳定段"与"动态段"分开
        # 传来(system / system_dynamic),把 system 拆成 2 个 text block —— 第一块含
        # cache_control 断点(只缓存稳定段),第二块不带(动态段每步变化,不污染前缀)。
        # system_dynamic 为空 / None → 走原单 block 路径(向后兼容,既有 caller 不破)。
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
        # 方案 C(spec §5):图片只在此处物化成 wire 格式；无附件消息行为与现状逐字节一致。
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
            if u.get("cache_read_input_tokens") is not None:
                last_usage["cache_read"] = int(u.get("cache_read_input_tokens") or 0)
            if u.get("cache_creation_input_tokens") is not None:
                last_usage["cache_creation"] = int(u.get("cache_creation_input_tokens") or 0)
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
    """OpenAI Chat Completions(覆盖 OpenRouter / Ollama / LM Studio / vLLM / DeepSeek 等)。
    与 Anthropic 的差异:system 作首条消息(无顶层 system);Bearer 认证;
    流式 usage 需 stream_options.include_usage;SSE 走 choices[].delta.content。"""
    name = "openai"

    def endpoint(self, base_url: str) -> str:
        # 幂等:用户已粘贴完整 .../chat/completions 时不重复追加(防双拼)。
        b = base_url.rstrip("/")
        return b if b.endswith("/chat/completions") else b + "/chat/completions"

    def headers(self, key: str) -> dict[str, str]:
        return {"Authorization": f"Bearer {key}", "content-type": "application/json"}

    def payload(self, messages: list[dict], *, system: str, tier: Any,
                system_dynamic: str | None = None) -> dict[str, Any]:
        # OpenAI / OpenRouter / Ollama / LM Studio / vLLM / DeepSeek 走【自动前缀缓存】,
        # 无显式 cache_control 字段。把 stable + dynamic 合并为单条 system 消息,让自动
        # 缓存命中稳定前缀部分(若后端支持)。无 system_dynamic 时,行为与改造前一致。
        if system_dynamic:
            system_content = f"{system}\n\n{system_dynamic}"
        else:
            system_content = system
        coalesced = _coalesce_consecutive_roles(messages)
        # 方案 C(spec §5):图片只在此处物化成 wire 格式；无附件消息行为与现状逐字节一致。
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
