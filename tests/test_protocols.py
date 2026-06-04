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


def test_modelclient_selects_protocol_by_tier():
    from argos_agent.core.models import ModelClient
    mc = ModelClient.__new__(ModelClient)
    mc.tier = _tier(protocol="openai")
    mc._proto = get_protocol(mc.tier.protocol)
    assert mc._proto.name == "openai"


def test_coalesce_still_importable_from_models():
    # 向后兼容:旧测试/代码 from argos_agent.core.models import _coalesce_consecutive_roles
    from argos_agent.core.models import _coalesce_consecutive_roles as c
    assert c([{"role": "user", "content": "a"}, {"role": "user", "content": "b"}])[0]["content"] == "a\nb"


def test_openai_payload_system_as_message_and_stream_options():
    p = OpenAIProtocol()
    pl = p.payload([{"role": "user", "content": "a"}, {"role": "user", "content": "b"}],
                   system="sys", tier=_tier(protocol="openai", base="http://localhost:11434/v1"))
    assert pl["messages"][0] == {"role": "system", "content": "sys"}   # system 作首条消息
    assert pl["messages"][1]["content"] == "a\nb"                       # 其余 coalesced
    assert pl["model"] == "m" and pl["max_tokens"] == 99
    assert pl["stream"] is True and pl["stream_options"] == {"include_usage": True}


def test_openai_endpoint_and_headers():
    p = OpenAIProtocol()
    assert p.endpoint("http://localhost:11434/v1") == "http://localhost:11434/v1/chat/completions"
    assert p.headers("KEY")["Authorization"] == "Bearer KEY"


def test_openai_text_delta_and_done():
    p = OpenAIProtocol()
    assert p.text_delta({"choices": [{"delta": {"content": "hi"}}]}) == "hi"
    assert p.text_delta({"choices": [{"delta": {"role": "assistant"}}]}) == ""   # role-only 首块
    assert p.is_done({"choices": [{"finish_reason": "stop", "delta": {}}]}) is True
    assert p.is_done({"choices": [{"finish_reason": None, "delta": {"content": "x"}}]}) is False


def test_openai_capture_usage_maps_prompt_completion_cached():
    p = OpenAIProtocol()
    u = {"input_tokens": 0, "output_tokens": 0, "cache_read": 0, "cache_creation": 0}
    p.capture_usage({"usage": {"prompt_tokens": 120, "completion_tokens": 45,
                               "prompt_tokens_details": {"cached_tokens": 30}}}, u)
    assert u["input_tokens"] == 120 and u["output_tokens"] == 45 and u["cache_read"] == 30


import httpx, pytest
from argos_agent.core.models import ModelClient, CredentialPool


@pytest.mark.asyncio
async def test_openai_stream_end_to_end_mock():
    sse = (b'data: {"choices":[{"delta":{"role":"assistant"}}]}\n\n'
           b'data: {"choices":[{"delta":{"content":"he"}}]}\n\n'
           b'data: {"choices":[{"delta":{"content":"llo"}}]}\n\n'
           b'data: {"choices":[{"finish_reason":"stop","delta":{}}],'
           b'"usage":{"prompt_tokens":10,"completion_tokens":2}}\n\n'
           b'data: [DONE]\n\n')

    def handler(req: httpx.Request) -> httpx.Response:
        assert req.url.path.endswith("/chat/completions")
        assert req.headers["authorization"] == "Bearer K"
        return httpx.Response(200, content=sse)

    mc = ModelClient(tier=_tier(protocol="openai", base="http://x/v1"),
                     pool=CredentialPool(["K"]), transport=httpx.MockTransport(handler))
    out = "".join([c async for c in mc.stream([{"role": "user", "content": "hi"}], system="s")])
    assert out == "hello"
    assert mc.last_usage["input_tokens"] == 10 and mc.last_usage["output_tokens"] == 2
