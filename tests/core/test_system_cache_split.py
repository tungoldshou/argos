from __future__ import annotations

from argos.core.honesty import compose_system_pair
from argos.core.protocols import AnthropicProtocol, OpenAIProtocol
from argos.core.types import ModelTierName


def test_compose_system_pair_returns_safe_and_untrusted():
    safe = "HONESTY_SYSTEM ..."
    untrusted = "<UNTRUSTED>recall ...</UNTRUSTED>"
    s, d = compose_system_pair(safe, untrusted)
    assert s == safe
    assert d == untrusted


def test_compose_system_pair_empty_untrusted_still_returns_pair():
    s, d = compose_system_pair("safe", "")
    assert s == "safe"
    assert d == ""


def _tier():
    from argos.core.models import ModelTier
    return ModelTier(name="default", model="c", base_url="https://x", max_tokens=64)


def test_anthropic_payload_with_dynamic_splits_into_two_blocks():
    p = AnthropicProtocol()
    payload = p.payload(
        [{"role": "user", "content": "hi"}],
        system="STABLE_PREFIX",
        system_dynamic="<UNTRUSTED>recall</UNTRUSTED>",
        tier=_tier(),
    )
    assert isinstance(payload["system"], list)
    assert len(payload["system"]) == 2


def test_anthropic_stable_block_has_cache_control():
    p = AnthropicProtocol()
    payload = p.payload(
        [{"role": "user", "content": "hi"}],
        system="STABLE",
        system_dynamic="<UNTRUSTED>recall</UNTRUSTED>",
        tier=_tier(),
    )
    first = payload["system"][0]
    assert first["type"] == "text"
    assert first["text"] == "STABLE"
    assert first.get("cache_control") == {"type": "ephemeral"}


def test_anthropic_dynamic_block_has_no_cache_control():
    p = AnthropicProtocol()
    payload = p.payload(
        [{"role": "user", "content": "hi"}],
        system="STABLE",
        system_dynamic="<UNTRUSTED>recall X</UNTRUSTED>",
        tier=_tier(),
    )
    second = payload["system"][1]
    assert second["type"] == "text"
    assert second["text"] == "<UNTRUSTED>recall X</UNTRUSTED>"
    assert "cache_control" not in second, "动态段不得带 cache_control(防污染前缀)"


def test_anthropic_legacy_single_string_path_unchanged():
    p = AnthropicProtocol()
    payload = p.payload(
        [{"role": "user", "content": "hi"}],
        system="ALL",
        system_dynamic=None,
        tier=_tier(),
    )
    assert isinstance(payload["system"], list)
    assert len(payload["system"]) == 1
    assert payload["system"][0]["text"] == "ALL"
    assert payload["system"][0].get("cache_control") == {"type": "ephemeral"}


def test_anthropic_empty_dynamic_uses_single_block():
    p = AnthropicProtocol()
    payload = p.payload(
        [{"role": "user", "content": "hi"}],
        system="STABLE_ONLY",
        system_dynamic="",
        tier=_tier(),
    )
    assert len(payload["system"]) == 1
    assert payload["system"][0]["text"] == "STABLE_ONLY"


def test_openai_payload_combines_stable_and_dynamic_in_system_message():
    p = OpenAIProtocol()
    payload = p.payload(
        [{"role": "user", "content": "hi"}],
        system="STABLE",
        system_dynamic="DYNAMIC",
        tier=_tier(),
    )
    msgs = payload["messages"]
    assert msgs[0]["role"] == "system"
    assert "STABLE" in msgs[0]["content"]
    assert "DYNAMIC" in msgs[0]["content"]


def test_openai_no_cache_control_field_emitted():
    p = OpenAIProtocol()
    payload = p.payload(
        [{"role": "user", "content": "hi"}],
        system="S",
        system_dynamic="D",
        tier=_tier(),
    )
    def _walk(obj):
        if isinstance(obj, dict):
            for k, v in obj.items():
                if "cache_control" in k:
                    return k
                r = _walk(v)
                if r:
                    return r
        elif isinstance(obj, list):
            for x in obj:
                r = _walk(x)
                if r:
                    return r
        return None
    assert _walk(payload) is None, f"OpenAI 路径出现 cache_control 字段:{_walk(payload)}"


def test_openai_legacy_single_string_path_unchanged():
    p = OpenAIProtocol()
    payload = p.payload(
        [{"role": "user", "content": "hi"}],
        system="ALL",
        system_dynamic=None,
        tier=_tier(),
    )
    msgs = payload["messages"]
    assert msgs[0]["role"] == "system"
    assert msgs[0]["content"] == "ALL"
    assert "ALL" in msgs[0]["content"]


def test_model_client_passes_system_dynamic_through():
    from argos.core.models import CredentialPool, ModelClient
    tier = _tier()
    pool = CredentialPool(["k"])
    client = ModelClient(tier=tier, pool=pool)

    captured: dict = {}
    class _Spy:
        name = "anthropic"
        def payload(self, messages, *, system, tier, system_dynamic=None):
            captured.update({"messages": messages, "system": system,
                              "system_dynamic": system_dynamic, "tier": tier})
            return {"messages": messages, "system": system}
    client._proto = _Spy()
    payload = client._payload(
        [{"role": "user", "content": "x"}],
        system="STABLE",
        system_dynamic="DYNAMIC",
    )
    assert captured["system"] == "STABLE"
    assert captured["system_dynamic"] == "DYNAMIC"
    assert captured["tier"] is tier


def test_model_client_system_dynamic_default_none():
    from argos.core.models import CredentialPool, ModelClient
    pool = CredentialPool(["k"])
    client = ModelClient(tier=_tier(), pool=pool)

    captured: dict = {}
    class _Spy:
        name = "anthropic"
        def payload(self, messages, *, system, tier, system_dynamic=None):
            captured["system_dynamic"] = system_dynamic
            return {"messages": messages, "system": system}
    client._proto = _Spy()
    client._payload([{"role": "user", "content": "x"}], system="S")
    assert captured["system_dynamic"] is None
