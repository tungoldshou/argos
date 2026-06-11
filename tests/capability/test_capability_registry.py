"""CapabilityRegistry 测试（§5 能力模型）。

覆盖：
- 注册成功 / 重名拒绝 / risk=None 拒绝
- get() 成功 / KeyError
- names() 顺序
- by_kind() 过滤
- risk_table() 快照
- egress_hosts() 聚合（空/单/多/去重）
- visible_names() 角色过滤（all / developer）
- __len__ / __contains__
- 注册后注册表与原 Capability 无共享可变状态（不变式）
"""
from __future__ import annotations

import pytest

from argos_agent.capability.manifest import Capability
from argos_agent.capability.registry import CapabilityRegistry


# ------------------------------------------------------------------
# 辅助工厂
# ------------------------------------------------------------------

def _cap(
    name: str = "web_search",
    kind: str = "tool",
    risk: str | None = "low",
    egress_hosts: tuple[str, ...] = (),
    visibility: str = "all",
    reversible: bool | None = None,
) -> Capability:
    return Capability(
        name=name,
        kind=kind,  # type: ignore[arg-type]
        risk=risk,  # type: ignore[arg-type]
        egress_hosts=egress_hosts,
        visibility=visibility,  # type: ignore[arg-type]
        reversible=reversible,
    )


def _reg(*caps: Capability) -> CapabilityRegistry:
    """构造含指定 capabilities 的 registry。"""
    r = CapabilityRegistry()
    for cap in caps:
        r.register(cap)
    return r


# ------------------------------------------------------------------
# 注册 — 正常路径
# ------------------------------------------------------------------

def test_register_single():
    """单个 capability 注册成功。"""
    r = CapabilityRegistry()
    cap = _cap()
    r.register(cap)
    assert "web_search" in r
    assert len(r) == 1


def test_register_multiple_in_order():
    """多个 capability 按注册顺序保留。"""
    r = CapabilityRegistry()
    r.register(_cap("a", "tool", "low"))
    r.register(_cap("b", "mcp", "medium"))
    r.register(_cap("c", "skill", "high"))
    assert r.names() == ("a", "b", "c")


# ------------------------------------------------------------------
# 注册 — fail-closed
# ------------------------------------------------------------------

def test_register_duplicate_name_raises():
    """重名注册抛 ValueError（全局唯一约束）。"""
    r = CapabilityRegistry()
    r.register(_cap("web_search"))
    with pytest.raises(ValueError, match="web_search"):
        r.register(_cap("web_search"))


def test_register_none_risk_raises():
    """risk=None 注册期 fail-closed 抛 ValueError。"""
    r = CapabilityRegistry()
    cap = _cap(risk=None)
    with pytest.raises(ValueError, match="risk"):
        r.register(cap)


def test_register_none_risk_message_mentions_name():
    """错误消息应含 capability 名，方便排查。"""
    r = CapabilityRegistry()
    cap = _cap(name="mystery_tool", risk=None)
    with pytest.raises(ValueError, match="mystery_tool"):
        r.register(cap)


# ------------------------------------------------------------------
# get()
# ------------------------------------------------------------------

def test_get_existing():
    """get() 返回已注册的 Capability。"""
    cap = _cap("run_command", "tool", "high")
    r = _reg(cap)
    result = r.get("run_command")
    assert result is cap


def test_get_missing_raises_key_error():
    """get() 未知名抛 KeyError。"""
    r = CapabilityRegistry()
    with pytest.raises(KeyError, match="not_here"):
        r.get("not_here")


# ------------------------------------------------------------------
# names()
# ------------------------------------------------------------------

def test_names_empty():
    """空注册表返回空 tuple。"""
    r = CapabilityRegistry()
    assert r.names() == ()


def test_names_order_preserved():
    """names() 保持注册顺序。"""
    r = _reg(
        _cap("z", "tool", "low"),
        _cap("a", "mcp", "medium"),
        _cap("m", "skill", "high"),
    )
    assert r.names() == ("z", "a", "m")


# ------------------------------------------------------------------
# by_kind()
# ------------------------------------------------------------------

def test_by_kind_returns_matching():
    """by_kind('tool') 只返回 tool 类型。"""
    r = _reg(
        _cap("tool_a", "tool", "low"),
        _cap("mcp_b", "mcp", "medium"),
        _cap("tool_c", "tool", "high"),
    )
    result = r.by_kind("tool")
    assert len(result) == 2
    assert all(c.kind == "tool" for c in result)
    assert tuple(c.name for c in result) == ("tool_a", "tool_c")


def test_by_kind_empty_when_none_match():
    """by_kind() 无匹配返回空 tuple。"""
    r = _reg(_cap("web_search", "tool", "low"))
    assert r.by_kind("browser") == ()


@pytest.mark.parametrize("kind", [
    "tool", "mcp", "computer", "browser", "hook", "skill", "lsp", "plugin",
])
def test_by_kind_all_valid_kinds(kind):
    """每个合法 kind 都能用 by_kind 查询（不报错）。"""
    r = _reg(_cap(f"cap_{kind}", kind, "low"))
    result = r.by_kind(kind)  # type: ignore[arg-type]
    assert len(result) == 1
    assert result[0].kind == kind


# ------------------------------------------------------------------
# risk_table()
# ------------------------------------------------------------------

def test_risk_table_correct_mapping():
    """risk_table() 返回正确的 name → RiskLevel 映射。"""
    r = _reg(
        _cap("web_search", "tool", "low"),
        _cap("run_command", "tool", "high"),
        _cap("mcp_call", "mcp", "medium"),
    )
    table = r.risk_table()
    assert table == {
        "web_search": "low",
        "run_command": "high",
        "mcp_call": "medium",
    }


def test_risk_table_is_snapshot():
    """risk_table() 返回的字典是副本，修改不影响注册表。"""
    r = _reg(_cap("web_search", "tool", "low"))
    table = r.risk_table()
    table["web_search"] = "high"  # 修改副本
    # 原注册表不变
    assert r.get("web_search").risk == "low"


def test_risk_table_empty():
    """空注册表返回空 dict。"""
    r = CapabilityRegistry()
    assert r.risk_table() == {}


# ------------------------------------------------------------------
# egress_hosts()
# ------------------------------------------------------------------

def test_egress_hosts_empty_when_no_caps():
    """空注册表 egress_hosts() 返回空 frozenset。"""
    r = CapabilityRegistry()
    assert r.egress_hosts() == frozenset()


def test_egress_hosts_single_cap():
    """单个 cap 的 egress_hosts 正确聚合。"""
    cap = _cap("web_search", "tool", "low", egress_hosts=("duckduckgo.com",))
    r = _reg(cap)
    assert r.egress_hosts() == frozenset({"duckduckgo.com"})


def test_egress_hosts_multiple_caps_union():
    """多个 cap 的 egress_hosts 取并集。"""
    r = _reg(
        _cap("web_search", "tool", "low", egress_hosts=("duckduckgo.com",)),
        _cap("web_extract", "tool", "low", egress_hosts=("example.com",)),
    )
    assert r.egress_hosts() == frozenset({"duckduckgo.com", "example.com"})


def test_egress_hosts_deduplication():
    """两个 cap 声明同一个 host，只出现一次（frozenset 去重）。"""
    r = _reg(
        _cap("cap_a", "tool", "low", egress_hosts=("shared.com",)),
        _cap("cap_b", "mcp", "medium", egress_hosts=("shared.com",)),
    )
    hosts = r.egress_hosts()
    assert hosts == frozenset({"shared.com"})
    assert len(hosts) == 1


def test_egress_hosts_cap_with_no_egress():
    """无出网声明的 cap 不贡献 egress_hosts。"""
    r = _reg(
        _cap("local_tool", "tool", "low"),           # 无 egress
        _cap("web_tool", "tool", "low", egress_hosts=("api.example.com",)),
    )
    assert r.egress_hosts() == frozenset({"api.example.com"})


def test_egress_hosts_returns_frozenset():
    """egress_hosts() 返回 frozenset（不可变）。"""
    r = _reg(_cap("a", "tool", "low", egress_hosts=("x.com",)))
    result = r.egress_hosts()
    assert isinstance(result, frozenset)


# ------------------------------------------------------------------
# visible_names()
# ------------------------------------------------------------------

def test_visible_names_all_role_sees_only_all():
    """role='all' 只看到 visibility='all' 的能力。"""
    r = _reg(
        _cap("public_tool", "tool", "low", visibility="all"),
        _cap("lsp_action", "lsp", "low", visibility="developer"),
        _cap("plugin_x", "plugin", "low", visibility="developer"),
    )
    visible = r.visible_names("all")
    assert visible == ("public_tool",)


def test_visible_names_developer_sees_all():
    """role='developer' 看到全部能力（all + developer）。"""
    r = _reg(
        _cap("public_tool", "tool", "low", visibility="all"),
        _cap("lsp_action", "lsp", "low", visibility="developer"),
    )
    visible = r.visible_names("developer")
    assert set(visible) == {"public_tool", "lsp_action"}


def test_visible_names_preserves_registration_order():
    """visible_names() 保持注册顺序。"""
    r = _reg(
        _cap("first", "tool", "low", visibility="all"),
        _cap("second", "tool", "low", visibility="all"),
        _cap("third", "tool", "low", visibility="all"),
    )
    assert r.visible_names("all") == ("first", "second", "third")


def test_visible_names_empty_registry():
    """空注册表两种角色都返回空 tuple。"""
    r = CapabilityRegistry()
    assert r.visible_names("all") == ()
    assert r.visible_names("developer") == ()


# ------------------------------------------------------------------
# __len__ / __contains__
# ------------------------------------------------------------------

def test_len_empty():
    assert len(CapabilityRegistry()) == 0


def test_len_after_register():
    r = CapabilityRegistry()
    r.register(_cap("a"))
    r.register(_cap("b", "mcp", "medium"))
    assert len(r) == 2


def test_contains_registered():
    r = _reg(_cap("web_search"))
    assert "web_search" in r


def test_not_contains_unregistered():
    r = CapabilityRegistry()
    assert "web_search" not in r


# ------------------------------------------------------------------
# 不变式：注册表独立于 Capability 对象
# ------------------------------------------------------------------

def test_registry_holds_same_object():
    """register() 存储的是同一个 Capability 对象，无拷贝。"""
    cap = _cap("run_command", "tool", "high")
    r = _reg(cap)
    assert r.get("run_command") is cap


def test_names_returns_tuple_not_list():
    """names() 返回 tuple，保证外部不能 append。"""
    r = _reg(_cap())
    result = r.names()
    assert isinstance(result, tuple)


def test_by_kind_returns_tuple_not_list():
    """by_kind() 返回 tuple（不可变视图）。"""
    r = _reg(_cap("t", "tool", "low"))
    result = r.by_kind("tool")
    assert isinstance(result, tuple)
