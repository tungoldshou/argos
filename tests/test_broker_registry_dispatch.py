from __future__ import annotations

import asyncio

import pytest

from argos.approval import ApprovalGate, ApprovalLevel
from argos.capability import Capability, CapabilityRegistry, register_builtins
from argos.sandbox.broker import CapabilityBroker
from argos.sandbox.egress import EgressPolicy
from argos.tools.receipts import ReceiptSigner


# ── helpers ────────────────────────────────────────────────────────────────

def _make_broker(
    level: ApprovalLevel = ApprovalLevel.AUTO,
    registry: CapabilityRegistry | None = None,
) -> CapabilityBroker:
    gate = ApprovalGate(level=level)
    egress = EgressPolicy(
        llm_hosts={"api.minimaxi.com"},
        search_hosts={"duckduckgo.com"},
        mcp_hosts=set(),
    )
    signer = ReceiptSigner(key=b"test-key-p2")
    return CapabilityBroker(
        gate=gate, egress=egress, signer=signer, registry=registry,
    )



@pytest.mark.asyncio
async def test_registry_none_unknown_action_rejected():
    br = _make_broker(registry=None)
    res = await br.request("totally_unknown", {})
    assert "未知" in res or "不支持" in res


@pytest.mark.asyncio
async def test_registry_none_web_search_passes_egress():
    import argos.web as _w

    br = _make_broker(registry=None)
    import unittest.mock as mock
    fake_result = {"success": True, "results": [{"title": "t", "url": "u", "snippet": "s"}]}
    with mock.patch.object(_w, "search", return_value=fake_result):
        res = await br.request("web_search", {"query": "hello", "limit": 1})
    assert "egress" not in res and "未知" not in res



def test_registry_risk_table_overrides_builtin():
    reg = CapabilityRegistry()
    cap = Capability(name="web_search", kind="tool", risk="high", dispatch=None)
    reg.register(cap)
    table = reg.risk_table()
    assert table["web_search"] == "high"



def test_execute_calls_dispatch_when_set():
    called_with: dict = {}

    def my_dispatch(args: dict, run_ctx) -> str:
        called_with["args"] = args
        called_with["ctx"] = run_ctx
        return "dispatched!"

    reg = CapabilityRegistry()
    reg.register(Capability(name="custom_tool", kind="tool", risk="low", dispatch=my_dispatch))

    gate = ApprovalGate(level=ApprovalLevel.AUTO)
    egress = EgressPolicy(llm_hosts=set(), search_hosts=set(), mcp_hosts=set())
    signer = ReceiptSigner(key=b"k")
    br = CapabilityBroker(gate=gate, egress=egress, signer=signer, registry=reg)

    result, exit_code = br._execute("custom_tool", {"x": 1}, _gated=True)
    assert result == "dispatched!"
    assert exit_code is None
    assert called_with["args"] == {"x": 1}
    assert called_with["ctx"] is None



def test_execute_fallthrough_when_dispatch_none(monkeypatch):
    captured: dict = {}

    def fake_run(command, *, workspace=None, allow_network=False):
        captured["cmd"] = command
        return ("ok", 0)

    monkeypatch.setattr("argos.tools.shell.run_command", fake_run)

    reg = CapabilityRegistry()
    reg.register(Capability(name="run_command", kind="tool", risk="high", dispatch=None))

    gate = ApprovalGate(level=ApprovalLevel.AUTO)
    egress = EgressPolicy(llm_hosts=set(), search_hosts=set(), mcp_hosts=set())
    br = CapabilityBroker(gate=gate, egress=egress, signer=ReceiptSigner(key=b"k"), registry=reg)

    result, _ = br._execute("run_command", {"command": "echo test"})
    assert captured["cmd"] == "echo test"
    assert "ok" in result



def test_execute_fallthrough_when_not_in_registry(monkeypatch):
    captured: dict = {}

    def fake_run(command, *, workspace=None, allow_network=False):
        captured["cmd"] = command
        return ("ok", 0)

    monkeypatch.setattr("argos.tools.shell.run_command", fake_run)

    reg = CapabilityRegistry()
    reg.register(Capability(name="custom_other", kind="tool", risk="low"))

    gate = ApprovalGate(level=ApprovalLevel.AUTO)
    egress = EgressPolicy(llm_hosts=set(), search_hosts=set(), mcp_hosts=set())
    br = CapabilityBroker(gate=gate, egress=egress, signer=ReceiptSigner(key=b"k"), registry=reg)

    result, _ = br._execute("run_command", {"command": "ls"})
    assert captured.get("cmd") == "ls"



@pytest.mark.asyncio
async def test_lsp_action_allowed_via_registry(monkeypatch):
    reg = CapabilityRegistry()
    egress = EgressPolicy(llm_hosts=set(), search_hosts=set(), mcp_hosts=set())
    register_builtins(reg, egress=egress)

    gate = ApprovalGate(level=ApprovalLevel.AUTO)
    signer = ReceiptSigner(key=b"lsp-test-key")
    br = CapabilityBroker(gate=gate, egress=egress, signer=signer, registry=reg)

    def fake_execute(action: str, args: dict, run_ctx=None, *,
                     _gated: bool = False, allow_network: bool = False):
        if action.startswith("lsp_"):
            return f"lsp_result:{action}", None
        raise AssertionError(f"未预期的 action: {action}")

    br._execute = fake_execute  # type: ignore[method-assign]

    res = await br.request("lsp_definition", {
        "file": "a.py", "line": 1, "col": 1,
    })
    assert "未知" not in res and "不支持" not in res
    assert "lsp_result" in res


@pytest.mark.asyncio
async def test_lsp_action_rejected_without_registry():
    br = _make_broker(registry=None)
    res = await br.request("lsp_definition", {"file": "a.py", "line": 1, "col": 1})
    assert "未知" in res or "不支持" in res


# ── 7. EgressPolicy.add_hosts ─────────────────────────────────────────────

def test_egress_add_hosts_allows_new_host():
    egress = EgressPolicy(llm_hosts=set(), search_hosts=set(), mcp_hosts=set())
    assert not egress.allowed("new.example.com")
    egress.add_hosts({"new.example.com"})
    assert egress.allowed("new.example.com")


def test_egress_add_hosts_idempotent():
    egress = EgressPolicy(llm_hosts=set(), search_hosts=set(), mcp_hosts=set())
    egress.add_hosts({"a.example.com"})
    egress.add_hosts({"a.example.com"})
    assert egress.allowed("a.example.com")


def test_egress_add_hosts_fail_closed_other_hosts():
    egress = EgressPolicy(llm_hosts=set(), search_hosts=set(), mcp_hosts=set())
    egress.add_hosts({"allowed.com"})
    assert not egress.allowed("blocked.com")


def test_egress_add_hosts_with_url():
    egress = EgressPolicy(llm_hosts=set(), search_hosts=set(), mcp_hosts=set())
    egress.add_hosts({"https://api.example.com/v1"})
    assert egress.allowed("api.example.com")


def test_egress_add_hosts_ignores_empty():
    egress = EgressPolicy(llm_hosts=set(), search_hosts=set(), mcp_hosts=set())
    egress.add_hosts({"", "  "})
    assert not egress.allowed("")



def test_register_builtins_updates_egress_for_search():
    reg = CapabilityRegistry()
    egress = EgressPolicy(llm_hosts=set(), search_hosts=set(), mcp_hosts=set())
    assert not egress.allowed("duckduckgo.com")
    register_builtins(reg, egress=egress)
    assert egress.allowed("duckduckgo.com")
    assert egress.allowed("api.tavily.com")


def test_register_builtins_lsp_actions_in_registry():
    reg = CapabilityRegistry()
    register_builtins(reg)
    lsp_actions = [
        "lsp_definition", "lsp_references", "lsp_hover",
        "lsp_document_symbols", "lsp_workspace_symbols", "lsp_diagnostics",
    ]
    for name in lsp_actions:
        assert name in reg, f"{name} 应在 registry"
        cap = reg.get(name)
        assert cap.kind == "lsp"
        assert cap.risk == "low"
        assert cap.visibility == "developer"


def test_register_builtins_idempotent():
    reg = CapabilityRegistry()
    register_builtins(reg)
    register_builtins(reg)
    count_first = len(reg)
    register_builtins(reg)
    assert len(reg) == count_first



def test_app_factory_components_has_registry(monkeypatch, tmp_path):
    import argos.config as _cfg
    from argos.core.models import ModelTier
    fake_tier = ModelTier(
        name="fake", model="claude-fake-1",
        base_url="https://fake.anthropic.com", max_tokens=4096,
    )
    monkeypatch.setattr(_cfg, "active_tier", lambda: fake_tier)
    monkeypatch.setattr(_cfg, "active_key", lambda: "sk-fake-key")
    monkeypatch.setattr(_cfg, "active_embedder", lambda: None)

    from argos.app_factory import build_components
    c = build_components(workspace=str(tmp_path))
    try:
        assert c.registry is not None
        assert len(c.registry) > 0
        assert "lsp_definition" in c.registry
        assert c.broker._registry is c.registry
    finally:
        c.close()


def test_build_run_stack_shares_registry(monkeypatch, tmp_path):
    import argos.config as _cfg
    from argos.core.models import ModelTier
    fake_tier = ModelTier(
        name="fake", model="claude-fake-1",
        base_url="https://fake.anthropic.com", max_tokens=4096,
    )
    monkeypatch.setattr(_cfg, "active_tier", lambda: fake_tier)
    monkeypatch.setattr(_cfg, "active_key", lambda: "sk-fake-key")
    monkeypatch.setattr(_cfg, "active_embedder", lambda: None)

    from argos.app_factory import build_components, build_run_stack
    c = build_components(workspace=str(tmp_path))
    try:
        stack = build_run_stack(c)
        try:
            assert stack.broker._registry is c.registry
        finally:
            stack.close()
    finally:
        c.close()



def test_dispatch_capability_blocked_via_direct_execute():
    def my_dispatch(args: dict, run_ctx) -> str:
        return "dispatched!"

    reg = CapabilityRegistry()
    reg.register(Capability(name="custom_gated", kind="tool", risk="low", dispatch=my_dispatch))

    gate = ApprovalGate(level=ApprovalLevel.AUTO)
    egress = EgressPolicy(llm_hosts=set(), search_hosts=set(), mcp_hosts=set())
    signer = ReceiptSigner(key=b"k")
    br = CapabilityBroker(gate=gate, egress=egress, signer=signer, registry=reg)

    with pytest.raises(PermissionError, match="broker.request"):
        br._execute("custom_gated", {"x": 1})


@pytest.mark.asyncio
async def test_dispatch_capability_allowed_via_request():
    def my_dispatch(args: dict, run_ctx) -> str:
        return f"dispatched:{args.get('x')}"

    reg = CapabilityRegistry()
    reg.register(Capability(name="custom_gated", kind="tool", risk="low", dispatch=my_dispatch))

    gate = ApprovalGate(level=ApprovalLevel.AUTO)
    egress = EgressPolicy(llm_hosts=set(), search_hosts=set(), mcp_hosts=set())
    signer = ReceiptSigner(key=b"k")
    br = CapabilityBroker(gate=gate, egress=egress, signer=signer, registry=reg)

    res = await br.request("custom_gated", {"x": 42})
    assert "dispatched:42" in res



def test_build_run_stack_egress_includes_registry_hosts(monkeypatch, tmp_path):
    import argos.config as _cfg
    from argos.core.models import ModelTier
    fake_tier = ModelTier(
        name="fake", model="claude-fake-1",
        base_url="https://fake.anthropic.com", max_tokens=4096,
    )
    monkeypatch.setattr(_cfg, "active_tier", lambda: fake_tier)
    monkeypatch.setattr(_cfg, "active_key", lambda: "sk-fake-key")
    monkeypatch.setattr(_cfg, "active_embedder", lambda: None)

    from argos.app_factory import build_components, build_run_stack
    c = build_components(workspace=str(tmp_path))
    try:
        from argos.capability import Capability
        c.registry.register(Capability(
            name="extra_web_tool",
            kind="tool",
            risk="low",
            egress_hosts=("extra.example.com",),
        ))

        stack = build_run_stack(c)
        try:
            assert stack.broker._egress.allowed("extra.example.com"), (
                "per-run egress 未合并 registry.egress_hosts()"
            )
            assert not stack.broker._egress.allowed("notregistered.example.com"), (
                "per-run egress 对未声明 host 应拒绝"
            )
        finally:
            stack.close()
    finally:
        c.close()


def test_build_run_stack_egress_excludes_wildcard(monkeypatch, tmp_path):
    import argos.config as _cfg
    from argos.core.models import ModelTier
    fake_tier = ModelTier(
        name="fake", model="claude-fake-1",
        base_url="https://fake.anthropic.com", max_tokens=4096,
    )
    monkeypatch.setattr(_cfg, "active_tier", lambda: fake_tier)
    monkeypatch.setattr(_cfg, "active_key", lambda: "sk-fake-key")
    monkeypatch.setattr(_cfg, "active_embedder", lambda: None)

    from argos.app_factory import build_components, build_run_stack
    c = build_components(workspace=str(tmp_path))
    try:
        from argos.capability import Capability
        c.registry.register(Capability(
            name="wildcard_tool",
            kind="tool",
            risk="medium",
            egress_hosts=("*",),
        ))

        stack = build_run_stack(c)
        try:
            assert not stack.broker._egress.allowed("arbitrary.random.host"), (
                "通配 '*' 不应使任意 host 通过 egress"
            )
        finally:
            stack.close()
    finally:
        c.close()



class TestEgressManifestDriven:

    def test_no_registry_returns_builtin_set(self):
        from argos.sandbox.broker import _NETWORK_ACTIONS
        broker = _make_broker(registry=None)
        derived = broker._derive_network_actions()
        assert derived == set(_NETWORK_ACTIONS), (
            "registry=None 时 _derive_network_actions 必须返回原 _NETWORK_ACTIONS"
        )

    def test_builtin_registry_derives_superset_of_original(self):
        from argos.sandbox.broker import _NETWORK_ACTIONS
        reg = CapabilityRegistry()
        register_builtins(reg)
        broker = _make_broker(registry=reg)
        derived = broker._derive_network_actions()
        missing = set(_NETWORK_ACTIONS) - derived
        assert not missing, (
            f"派生集合缺少原 _NETWORK_ACTIONS 中的动作: {missing}\n"
            f"派生集合: {derived}  原集合: {_NETWORK_ACTIONS}"
        )

    def test_custom_egress_cap_enters_derived_set(self):
        reg = CapabilityRegistry()
        reg.register(Capability(
            name="my_api_call",
            kind="tool",
            risk="medium",
            egress_hosts=("api.example.com",),
        ))
        broker = _make_broker(registry=reg)
        derived = broker._derive_network_actions()
        assert "my_api_call" in derived, (
            "声明了 egress_hosts 的自定义能力必须进 _derive_network_actions 的结果"
        )

    def test_no_egress_cap_not_in_derived_set(self):
        from argos.sandbox.broker import _NETWORK_ACTIONS
        reg = CapabilityRegistry()
        reg.register(Capability(
            name="local_tool",
            kind="tool",
            risk="low",
            egress_hosts=(),
        ))
        broker = _make_broker(registry=reg)
        derived = broker._derive_network_actions()
        assert "local_tool" not in derived
        assert set(_NETWORK_ACTIONS).issubset(derived)

    def test_wildcard_egress_enters_derived_set(self):
        reg = CapabilityRegistry()
        reg.register(Capability(
            name="dynamic_web_call",
            kind="tool",
            risk="medium",
            egress_hosts=("*",),
        ))
        broker = _make_broker(registry=reg)
        derived = broker._derive_network_actions()
        assert "dynamic_web_call" in derived
