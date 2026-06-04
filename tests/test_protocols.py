import json
from argos_agent.core.protocols import (
    get_protocol, AnthropicProtocol, OpenAIProtocol, _coalesce_consecutive_roles,
)
from argos_agent.core.models import ModelTier


def _tier(protocol="anthropic", base="https://api.x.com"):
    return ModelTier(name="t", model="m", base_url=base, max_tokens=99,
                     context_window=1000, protocol=protocol)


def test_get_protocol_returns_right_adapter():
    assert isinstance(get_protocol("anthropic"), AnthropicProtocol)
    assert isinstance(get_protocol("openai"), OpenAIProtocol)


def test_anthropic_payload_system_toplevel_and_coalesced():
    p = AnthropicProtocol()
    pl = p.payload([{"role": "user", "content": "a"}, {"role": "user", "content": "b"}],
                   system="sys", tier=_tier())
    assert pl["system"] == "sys"
    assert pl["model"] == "m" and pl["max_tokens"] == 99 and pl["stream"] is True
    assert len(pl["messages"]) == 1 and pl["messages"][0]["content"] == "a\nb"  # coalesced


def test_anthropic_endpoint_and_headers():
    p = AnthropicProtocol()
    assert p.endpoint("https://api.x.com/anthropic/") == "https://api.x.com/anthropic/v1/messages"
    h = p.headers("KEY")
    assert h["x-api-key"] == "KEY" and h["anthropic-version"] == "2023-06-01"


def test_anthropic_text_delta_and_usage():
    p = AnthropicProtocol()
    assert p.text_delta({"type": "content_block_delta",
                         "delta": {"type": "text_delta", "text": "hi"}}) == "hi"
    u = {"input_tokens": 0, "output_tokens": 0, "cache_read": 0, "cache_creation": 0}
    p.capture_usage({"type": "message_start", "message": {"usage": {
        "input_tokens": 0, "cache_read_input_tokens": 179, "cache_creation_input_tokens": 5}}}, u)
    assert u["cache_read"] == 179 and u["cache_creation"] == 5
    p.capture_usage({"type": "message_delta", "usage": {"input_tokens": 65, "output_tokens": 41}}, u)
    assert u["input_tokens"] == 65 and u["output_tokens"] == 41
