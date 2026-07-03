"""Internal documentation."""
from __future__ import annotations

import pytest

from argos.capability.manifest import Capability
from argos.capability.registry import CapabilityRegistry


# ------------------------------------------------------------------
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
    """Internal documentation."""
    r = CapabilityRegistry()
    for cap in caps:
        r.register(cap)
    return r


# ------------------------------------------------------------------
# ------------------------------------------------------------------

def test_register_single():
    """Internal documentation."""
    r = CapabilityRegistry()
    cap = _cap()
    r.register(cap)
    assert "web_search" in r
    assert len(r) == 1


def test_register_multiple_in_order():
    """Internal documentation."""
    r = CapabilityRegistry()
    r.register(_cap("a", "tool", "low"))
    r.register(_cap("b", "mcp", "medium"))
    r.register(_cap("c", "skill", "high"))
    assert r.names() == ("a", "b", "c")


# ------------------------------------------------------------------
# ------------------------------------------------------------------

def test_register_duplicate_name_raises():
    """Internal documentation."""
    r = CapabilityRegistry()
    r.register(_cap("web_search"))
    with pytest.raises(ValueError, match="web_search"):
        r.register(_cap("web_search"))


def test_register_none_risk_raises():
    """Internal documentation."""
    r = CapabilityRegistry()
    cap = _cap(risk=None)
    with pytest.raises(ValueError, match="risk"):
        r.register(cap)


def test_register_none_risk_message_mentions_name():
    """Internal documentation."""
    r = CapabilityRegistry()
    cap = _cap(name="mystery_tool", risk=None)
    with pytest.raises(ValueError, match="mystery_tool"):
        r.register(cap)


# ------------------------------------------------------------------
# get()
# ------------------------------------------------------------------

def test_get_existing():
    """Internal documentation."""
    cap = _cap("run_command", "tool", "high")
    r = _reg(cap)
    result = r.get("run_command")
    assert result is cap


def test_get_missing_raises_key_error():
    """Internal documentation."""
    r = CapabilityRegistry()
    with pytest.raises(KeyError, match="not_here"):
        r.get("not_here")


# ------------------------------------------------------------------
# names()
# ------------------------------------------------------------------

def test_names_empty():
    """Internal documentation."""
    r = CapabilityRegistry()
    assert r.names() == ()


def test_names_order_preserved():
    """Internal documentation."""
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
    """Internal documentation."""
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
    """Internal documentation."""
    r = _reg(_cap("web_search", "tool", "low"))
    assert r.by_kind("browser") == ()


@pytest.mark.parametrize("kind", [
    "tool", "mcp", "computer", "browser", "hook", "skill", "lsp", "plugin",
])
def test_by_kind_all_valid_kinds(kind):
    """Internal documentation."""
    r = _reg(_cap(f"cap_{kind}", kind, "low"))
    result = r.by_kind(kind)  # type: ignore[arg-type]
    assert len(result) == 1
    assert result[0].kind == kind


# ------------------------------------------------------------------
# risk_table()
# ------------------------------------------------------------------

def test_risk_table_correct_mapping():
    """Internal documentation."""
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
    """Internal documentation."""
    r = _reg(_cap("web_search", "tool", "low"))
    table = r.risk_table()
    table["web_search"] = "high"
    assert r.get("web_search").risk == "low"


def test_risk_table_empty():
    """Internal documentation."""
    r = CapabilityRegistry()
    assert r.risk_table() == {}


# ------------------------------------------------------------------
# egress_hosts()
# ------------------------------------------------------------------

def test_egress_hosts_empty_when_no_caps():
    """Internal documentation."""
    r = CapabilityRegistry()
    assert r.egress_hosts() == frozenset()


def test_egress_hosts_single_cap():
    """Internal documentation."""
    cap = _cap("web_search", "tool", "low", egress_hosts=("duckduckgo.com",))
    r = _reg(cap)
    assert r.egress_hosts() == frozenset({"duckduckgo.com"})


def test_egress_hosts_multiple_caps_union():
    """Internal documentation."""
    r = _reg(
        _cap("web_search", "tool", "low", egress_hosts=("duckduckgo.com",)),
        _cap("web_extract", "tool", "low", egress_hosts=("example.com",)),
    )
    assert r.egress_hosts() == frozenset({"duckduckgo.com", "example.com"})


def test_egress_hosts_deduplication():
    """Internal documentation."""
    r = _reg(
        _cap("cap_a", "tool", "low", egress_hosts=("shared.com",)),
        _cap("cap_b", "mcp", "medium", egress_hosts=("shared.com",)),
    )
    hosts = r.egress_hosts()
    assert hosts == frozenset({"shared.com"})
    assert len(hosts) == 1


def test_egress_hosts_cap_with_no_egress():
    """Internal documentation."""
    r = _reg(
        _cap("local_tool", "tool", "low"),
        _cap("web_tool", "tool", "low", egress_hosts=("api.example.com",)),
    )
    assert r.egress_hosts() == frozenset({"api.example.com"})


def test_egress_hosts_returns_frozenset():
    """Internal documentation."""
    r = _reg(_cap("a", "tool", "low", egress_hosts=("x.com",)))
    result = r.egress_hosts()
    assert isinstance(result, frozenset)


# ------------------------------------------------------------------
# visible_names()
# ------------------------------------------------------------------

def test_visible_names_all_role_sees_only_all():
    """Internal documentation."""
    r = _reg(
        _cap("public_tool", "tool", "low", visibility="all"),
        _cap("lsp_action", "lsp", "low", visibility="developer"),
        _cap("plugin_x", "plugin", "low", visibility="developer"),
    )
    visible = r.visible_names("all")
    assert visible == ("public_tool",)


def test_visible_names_developer_sees_all():
    """Internal documentation."""
    r = _reg(
        _cap("public_tool", "tool", "low", visibility="all"),
        _cap("lsp_action", "lsp", "low", visibility="developer"),
    )
    visible = r.visible_names("developer")
    assert set(visible) == {"public_tool", "lsp_action"}


def test_visible_names_preserves_registration_order():
    """Internal documentation."""
    r = _reg(
        _cap("first", "tool", "low", visibility="all"),
        _cap("second", "tool", "low", visibility="all"),
        _cap("third", "tool", "low", visibility="all"),
    )
    assert r.visible_names("all") == ("first", "second", "third")


def test_visible_names_empty_registry():
    """Internal documentation."""
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
# ------------------------------------------------------------------

def test_registry_holds_same_object():
    """Internal documentation."""
    cap = _cap("run_command", "tool", "high")
    r = _reg(cap)
    assert r.get("run_command") is cap


def test_names_returns_tuple_not_list():
    """Internal documentation."""
    r = _reg(_cap())
    result = r.names()
    assert isinstance(result, tuple)


def test_by_kind_returns_tuple_not_list():
    """Internal documentation."""
    r = _reg(_cap("t", "tool", "low"))
    result = r.by_kind("tool")
    assert isinstance(result, tuple)
