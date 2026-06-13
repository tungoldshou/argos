"""系统提示 cache 拆分验收 — 任务:并行子 agent 共用稳定前缀,Anthropic 协议打 cache_control 断点。

关键设计:
- safe 段 = 无 recall(HONESTY + env + tool_signatures + 契约 + MCP 摘要)
- untrusted 段 = 有 recall(skill bodies + memory lines)
- Anthropic:把 system 拆成 2 块,只在 stable(无 recall)上打 cache_control
- OpenAI:无 cache_control 字段,合并为单条 system message(自动前缀缓存,无需标记)
- 旧调用(无 system_dynamic)走单 block 路径,既有 1753 测试不破
"""
from __future__ import annotations

from argos.core.honesty import compose_system_pair
from argos.core.protocols import AnthropicProtocol, OpenAIProtocol
from argos.core.types import ModelTierName


# ── compose_system_pair 验收 ──────────────────────────────────
def test_compose_system_pair_returns_safe_and_untrusted():
    """compose_system_pair 显式化"稳定 vs 动态"边界,本任务不重组内容,只把 (safe, untrusted) 透传。"""
    safe = "HONESTY_SYSTEM ..."
    untrusted = "<UNTRUSTED>recall ...</UNTRUSTED>"
    s, d = compose_system_pair(safe, untrusted)
    assert s == safe
    assert d == untrusted


def test_compose_system_pair_empty_untrusted_still_returns_pair():
    """untrusted 为空时,稳定/动态都存在(动态为空字符串),协议层据此判"无动态尾巴"。"""
    s, d = compose_system_pair("safe", "")
    assert s == "safe"
    assert d == ""


# ── AnthropicProtocol 双块验收 ────────────────────────────────
def _tier():
    from argos.core.models import ModelTier
    return ModelTier(name="default", model="c", base_url="https://x", max_tokens=64)


def test_anthropic_payload_with_dynamic_splits_into_two_blocks():
    """传 system_dynamic 非空 → payload['system'] 是 list,长度=2。"""
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
    """第一块(稳定段)含 cache_control.ephemeral。"""
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
    """第二块(动态段)无 cache_control 字段(每步原样发,前缀不被它污染)。"""
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
    """system_dynamic=None → 保持单 block 现状(向后兼容,既有 1753 测试走此路径)。"""
    p = AnthropicProtocol()
    payload = p.payload(
        [{"role": "user", "content": "hi"}],
        system="ALL",
        system_dynamic=None,
        tier=_tier(),
    )
    # 单 block 仍带 cache_control(原行为,缓存由 Anthropic 静默忽略短串,无害)
    assert isinstance(payload["system"], list)
    assert len(payload["system"]) == 1
    assert payload["system"][0]["text"] == "ALL"
    assert payload["system"][0].get("cache_control") == {"type": "ephemeral"}


def test_anthropic_empty_dynamic_uses_single_block():
    """system_dynamic=""(空字符串)→ 视为无动态段,单 block 路径(不产空块)。"""
    p = AnthropicProtocol()
    payload = p.payload(
        [{"role": "user", "content": "hi"}],
        system="STABLE_ONLY",
        system_dynamic="",
        tier=_tier(),
    )
    assert len(payload["system"]) == 1
    assert payload["system"][0]["text"] == "STABLE_ONLY"


# ── OpenAIProtocol 透传验收 ──────────────────────────────────
def test_openai_payload_combines_stable_and_dynamic_in_system_message():
    """OpenAI 协议无 cache_control;合并为单条 system 消息(自动前缀缓存,无需标记)。"""
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
    """OpenAI payload 字典内【无】任何 cache_control 键(防误加 + 显式声明"OpenAI 自动缓存,无需标记")。"""
    p = OpenAIProtocol()
    payload = p.payload(
        [{"role": "user", "content": "hi"}],
        system="S",
        system_dynamic="D",
        tier=_tier(),
    )
    # 全字典扫描(包含嵌套)无 cache_control 键
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
    """OpenAI 协议 + system_dynamic=None → 行为与改造前一致(单段 system 消息)。"""
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
    # 没有 dynamic 拼接污染
    assert "ALL" in msgs[0]["content"]


# ── ModelClient 透传验收 ──────────────────────────────────
def test_model_client_passes_system_dynamic_through():
    """ModelClient._payload(messages, system, system_dynamic) → 协议层收到 system_dynamic。"""
    from argos.core.models import CredentialPool, ModelClient
    tier = _tier()
    pool = CredentialPool(["k"])
    client = ModelClient(tier=tier, pool=pool)

    # 改协议层为 spy,捕获 kwargs
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
    """ModelClient 现有 caller 不传 system_dynamic → 默认 None(向后兼容,旧行为不变)。"""
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
