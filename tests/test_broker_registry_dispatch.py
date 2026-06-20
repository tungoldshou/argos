"""P2 broker dispatch 化测试 —— registry 接线、LSP bug 修复、EgressPolicy.add_hosts。

覆盖契约：
1. registry=None 时旧行为完全不变（兼容现有测试路径）。
2. registry 非 None 时 risk 先查 registry.risk_table()，内置 _RISK 作 fallback。
3. _execute：cap.dispatch 非 None → 调 dispatch，不走 if/elif。
4. _execute：cap.dispatch=None → fall through 到内置实现（行为保持）。
5. _execute：action 不在 registry → 走内置实现（fallthrough，不崩）。
6. LSP bug 修复：lsp_* 在 registry（via register_builtins）注册后经 broker.request 走通。
7. EgressPolicy.add_hosts：幂等、热更新、fail-closed 不变。
8. app_factory：AppComponents 持有 registry；build_run_stack 共享同一 registry 实例。
"""
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


# ── 1. registry=None：兼容旧行为 ──────────────────────────────────────────

@pytest.mark.asyncio
async def test_registry_none_unknown_action_rejected():
    """registry=None 时未知 action → fail-closed 拒（旧语义保持）。"""
    br = _make_broker(registry=None)
    res = await br.request("totally_unknown", {})
    assert "未知" in res or "不支持" in res


@pytest.mark.asyncio
async def test_registry_none_web_search_passes_egress():
    """registry=None 时内置 web_search 走旧路径（risk from _RISK）。"""
    import argos.web as _w

    br = _make_broker(registry=None)
    # monkeypatch 只能在函数里用；改用 unittest.mock
    import unittest.mock as mock
    fake_result = {"success": True, "results": [{"title": "t", "url": "u", "snippet": "s"}]}
    with mock.patch.object(_w, "search", return_value=fake_result):
        res = await br.request("web_search", {"query": "hello", "limit": 1})
    assert "egress" not in res and "未知" not in res


# ── 2. registry 非 None：risk 先查 registry_risk，fallback _RISK ────────────

def test_registry_risk_table_overrides_builtin():
    """registry.risk_table() 中的 risk 优先于 _RISK（可以覆盖内置 risk 等级）。"""
    reg = CapabilityRegistry()
    # 用与 _RISK["web_search"]="low" 不同的 "high" 注册同名能力 dispatch=None
    cap = Capability(name="web_search", kind="tool", risk="high", dispatch=None)
    reg.register(cap)
    table = reg.risk_table()
    assert table["web_search"] == "high"


# ── 3. _execute：cap.dispatch 非 None → 调 dispatch ──────────────────────

def test_execute_calls_dispatch_when_set():
    """dispatch 非 None → _execute 调 dispatch(args, run_ctx)。"""
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

    # _gated=True:模拟经 request() 管线调用(修复 1 要求 dispatch 只经 gated 路径触发)
    result, exit_code = br._execute("custom_tool", {"x": 1}, _gated=True)
    assert result == "dispatched!"
    assert exit_code is None
    assert called_with["args"] == {"x": 1}
    assert called_with["ctx"] is None   # run_ctx=None 默认


# ── 4. _execute：dispatch=None → fall through 到内置实现 ──────────────────

def test_execute_fallthrough_when_dispatch_none(monkeypatch):
    """cap.dispatch=None → broker._execute 走内置 run_command 实现。"""
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


# ── 5. _execute：action 不在 registry → 走内置（fallthrough） ─────────────

def test_execute_fallthrough_when_not_in_registry(monkeypatch):
    """action 不在 registry → _execute fall through 到 if/elif 内置实现。"""
    captured: dict = {}

    def fake_run(command, *, workspace=None, allow_network=False):
        captured["cmd"] = command
        return ("ok", 0)

    monkeypatch.setattr("argos.tools.shell.run_command", fake_run)

    reg = CapabilityRegistry()
    # registry 里只有别的能力，没有 run_command
    reg.register(Capability(name="custom_other", kind="tool", risk="low"))

    gate = ApprovalGate(level=ApprovalLevel.AUTO)
    egress = EgressPolicy(llm_hosts=set(), search_hosts=set(), mcp_hosts=set())
    br = CapabilityBroker(gate=gate, egress=egress, signer=ReceiptSigner(key=b"k"), registry=reg)

    result, _ = br._execute("run_command", {"command": "ls"})
    assert captured.get("cmd") == "ls"


# ── 6. LSP bug 修复：lsp_* 经 broker.request 走通 ──────────────────────────

@pytest.mark.asyncio
async def test_lsp_action_allowed_via_registry(monkeypatch):
    """LSP bug 修复：register_builtins 注册 lsp_* 后 broker.request 不再 fail-closed 拒。

    mock lsp._execute 内部的 lsp 调用，只验证 request 能通过 gating（不调真 pyright）。
    """
    reg = CapabilityRegistry()
    egress = EgressPolicy(llm_hosts=set(), search_hosts=set(), mcp_hosts=set())
    register_builtins(reg, egress=egress)

    gate = ApprovalGate(level=ApprovalLevel.AUTO)
    signer = ReceiptSigner(key=b"lsp-test-key")
    br = CapabilityBroker(gate=gate, egress=egress, signer=signer, registry=reg)

    # monkeypatch broker._execute 的 LSP 分支（不启动真 pyright）
    # _gated / allow_network 是 keyword-only 参数，fake 需接受以兼容当前签名
    def fake_execute(action: str, args: dict, run_ctx=None, *,
                     _gated: bool = False, allow_network: bool = False):
        if action.startswith("lsp_"):
            return f"lsp_result:{action}", None
        raise AssertionError(f"未预期的 action: {action}")

    br._execute = fake_execute  # type: ignore[method-assign]

    res = await br.request("lsp_definition", {
        "file": "a.py", "line": 1, "col": 1,
    })
    # 关键：不是 fail-closed 拒绝串（修 bug 前会返回 "错误：未知/不支持的特权动作"）
    assert "未知" not in res and "不支持" not in res
    assert "lsp_result" in res


@pytest.mark.asyncio
async def test_lsp_action_rejected_without_registry():
    """对照组：registry=None 时 lsp_definition 走旧路径，_RISK 无此 action → fail-closed 拒。"""
    br = _make_broker(registry=None)
    res = await br.request("lsp_definition", {"file": "a.py", "line": 1, "col": 1})
    # 旧行为：lsp_* 不在 _RISK → 被拒
    assert "未知" in res or "不支持" in res


# ── 7. EgressPolicy.add_hosts ─────────────────────────────────────────────

def test_egress_add_hosts_allows_new_host():
    """add_hosts 加白后 allowed() 返回 True。"""
    egress = EgressPolicy(llm_hosts=set(), search_hosts=set(), mcp_hosts=set())
    assert not egress.allowed("new.example.com")
    egress.add_hosts({"new.example.com"})
    assert egress.allowed("new.example.com")


def test_egress_add_hosts_idempotent():
    """重复加白幂等，不抛不重复。"""
    egress = EgressPolicy(llm_hosts=set(), search_hosts=set(), mcp_hosts=set())
    egress.add_hosts({"a.example.com"})
    egress.add_hosts({"a.example.com"})   # 重复
    assert egress.allowed("a.example.com")


def test_egress_add_hosts_fail_closed_other_hosts():
    """add_hosts 加白 A，不影响 B 仍被拒（fail-closed 不变）。"""
    egress = EgressPolicy(llm_hosts=set(), search_hosts=set(), mcp_hosts=set())
    egress.add_hosts({"allowed.com"})
    assert not egress.allowed("blocked.com")


def test_egress_add_hosts_with_url():
    """add_hosts 接受 url 形式（提取 host 部分）。"""
    egress = EgressPolicy(llm_hosts=set(), search_hosts=set(), mcp_hosts=set())
    egress.add_hosts({"https://api.example.com/v1"})
    assert egress.allowed("api.example.com")


def test_egress_add_hosts_ignores_empty():
    """空字符串不加白（_host_of 返回空串，skip）。"""
    egress = EgressPolicy(llm_hosts=set(), search_hosts=set(), mcp_hosts=set())
    egress.add_hosts({"", "  "})
    # 不崩；allowed("") 返回 False
    assert not egress.allowed("")


# ── 8. register_builtins egress 热更新 ───────────────────────────────────

def test_register_builtins_updates_egress_for_search():
    """register_builtins 注册 web_search 时热更新 egress，使搜索 host 白名单生效。"""
    reg = CapabilityRegistry()
    egress = EgressPolicy(llm_hosts=set(), search_hosts=set(), mcp_hosts=set())
    # 初始：duckduckgo.com 不在白名单
    assert not egress.allowed("duckduckgo.com")
    register_builtins(reg, egress=egress)
    # register_builtins 后：web_search 的 egress_hosts 已热更新到 egress
    assert egress.allowed("duckduckgo.com")
    assert egress.allowed("api.tavily.com")


def test_register_builtins_lsp_actions_in_registry():
    """register_builtins 注册后，所有 lsp_* 动作都在 registry。"""
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
    """register_builtins 多次调用幂等（跳过已注册）。"""
    reg = CapabilityRegistry()
    register_builtins(reg)
    register_builtins(reg)   # 第二次不应 ValueError
    # 注册表大小不变
    count_first = len(reg)
    register_builtins(reg)
    assert len(reg) == count_first


# ── 9. app_factory registry 集成 ─────────────────────────────────────────

def test_app_factory_components_has_registry(monkeypatch, tmp_path):
    """build_components 返回的 AppComponents 含非 None registry（P2 内置注册）。"""
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
        # lsp_definition 应在 registry
        assert "lsp_definition" in c.registry
        # broker 持有同一 registry 引用
        assert c.broker._registry is c.registry
    finally:
        c.close()


def test_build_run_stack_shares_registry(monkeypatch, tmp_path):
    """build_run_stack 返回的 broker 共享 AppComponents 的同一 registry 实例。"""
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
            # per-run broker 应共享同一 registry 实例
            assert stack.broker._registry is c.registry
        finally:
            stack.close()
    finally:
        c.close()


# ── 10. 修复 1:dispatch 能力只能经 broker.request() 管线触发 ──────────────

def test_dispatch_capability_blocked_via_direct_execute():
    """直调 broker._execute 触发带 dispatch 的能力 → PermissionError(fail-closed 钉死)。"""
    def my_dispatch(args: dict, run_ctx) -> str:
        return "dispatched!"

    reg = CapabilityRegistry()
    reg.register(Capability(name="custom_gated", kind="tool", risk="low", dispatch=my_dispatch))

    gate = ApprovalGate(level=ApprovalLevel.AUTO)
    egress = EgressPolicy(llm_hosts=set(), search_hosts=set(), mcp_hosts=set())
    signer = ReceiptSigner(key=b"k")
    br = CapabilityBroker(gate=gate, egress=egress, signer=signer, registry=reg)

    # 直调 _execute(不经 request 管线)→ 必须抛 PermissionError
    with pytest.raises(PermissionError, match="broker.request"):
        br._execute("custom_gated", {"x": 1})


@pytest.mark.asyncio
async def test_dispatch_capability_allowed_via_request():
    """经 broker.request() 管线触发带 dispatch 的能力 → 正常执行,不 PermissionError。"""
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


# ── 11. 修复 2:build_run_stack per-run egress 从 registry 派生 ────────────

def test_build_run_stack_egress_includes_registry_hosts(monkeypatch, tmp_path):
    """build_run_stack 后,per-run egress 含 registry 声明的 egress_hosts(消灭双真值表)。"""
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
        # 向进程级 registry 注册一个带 egress_hosts 的额外能力
        from argos.capability import Capability
        c.registry.register(Capability(
            name="extra_web_tool",
            kind="tool",
            risk="low",
            egress_hosts=("extra.example.com",),
        ))

        stack = build_run_stack(c)
        try:
            # per-run broker 的 egress 必须对 registry 声明的 host 放行
            assert stack.broker._egress.allowed("extra.example.com"), (
                "per-run egress 未合并 registry.egress_hosts()"
            )
            # 未声明的 host 仍被拒(fail-closed 不变)
            assert not stack.broker._egress.allowed("notregistered.example.com"), (
                "per-run egress 对未声明 host 应拒绝"
            )
        finally:
            stack.close()
    finally:
        c.close()


def test_build_run_stack_egress_excludes_wildcard(monkeypatch, tmp_path):
    """egress_hosts 含 '*' 通配的能力,per-run egress 不因此开放所有 host(过滤通配)。"""
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
            # '*' 通配不应让任意 host 通过(fail-closed 方向不变)
            assert not stack.broker._egress.allowed("arbitrary.random.host"), (
                "通配 '*' 不应使任意 host 通过 egress"
            )
        finally:
            stack.close()
    finally:
        c.close()


# ── P2 egress manifest 驱动测试 ───────────────────────────────────────────────

class TestEgressManifestDriven:
    """_derive_network_actions 从 registry 派生 egress 动作集的正确性。"""

    def test_no_registry_returns_builtin_set(self):
        """registry=None 时 fallback = 原 _NETWORK_ACTIONS(行为零变更)。"""
        from argos.sandbox.broker import _NETWORK_ACTIONS
        broker = _make_broker(registry=None)
        derived = broker._derive_network_actions()
        assert derived == set(_NETWORK_ACTIONS), (
            "registry=None 时 _derive_network_actions 必须返回原 _NETWORK_ACTIONS"
        )

    def test_builtin_registry_derives_superset_of_original(self):
        """内置 registry(register_builtins)派生的集合是原 _NETWORK_ACTIONS 的超集。

        web_search / web_extract 在 builtins 中声明了 egress_hosts → 必须出现在派生集合中。
        此测试固化"派生集合 ⊇ 原集合"的硬回归保证。
        """
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
        """自定义能力声明 egress_hosts → 自动进派生集合,无需改 _NETWORK_ACTIONS。"""
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
        """未声明 egress_hosts 的能力不进派生集合(只含 _NETWORK_ACTIONS 兜底)。"""
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
        """egress_hosts=('*',) 通配 → 能力进派生集合(让 broker 走 egress 检查路径)。"""
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
