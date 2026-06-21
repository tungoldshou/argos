"""tests/test_lsp_server_routing.py — broker LSP 工具按文件扩展名路由测试。

Bug: sandbox/broker.py 的 _execute() LSP 分支全部硬编 server_name="python",
导致非 python 语言服务器配置了也用不上。

本套测试直接测试修复后的 broker._resolve_lsp_server() 辅助函数
(确认它按 file 扩展名路由正确 server),以及 broker._execute() 端到端路由。
"""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from argos.lsp.config import LspConfig, LspServerConfig
from argos.sandbox.broker import _resolve_lsp_server


# ── _resolve_lsp_server 单元测试 ──────────────────────────────────────────────

def _make_config_two_servers() -> LspConfig:
    """python + rust 两个 server 的配置。"""
    return LspConfig(
        version=1,
        servers={
            "python": LspServerConfig(
                command=("pyright-langserver", "--stdio"),
                filetypes=(".py", ".pyi"),
            ),
            "rust": LspServerConfig(
                command=("rust-analyzer",),
                filetypes=(".rs",),
            ),
        },
    )


def _make_manager(cfg: LspConfig) -> MagicMock:
    """mock LspManager,只暴露 .config 属性。"""
    m = MagicMock()
    m.config = cfg
    return m


def test_resolve_python_file_returns_python_server():
    """a.py → server_name='python'。"""
    cfg = _make_config_two_servers()
    mgr = _make_manager(cfg)
    name = _resolve_lsp_server(file="a.py", manager=mgr)
    assert name == "python"


def test_resolve_rust_file_returns_rust_server():
    """main.rs → server_name='rust',而非硬编 'python'。"""
    cfg = _make_config_two_servers()
    mgr = _make_manager(cfg)
    name = _resolve_lsp_server(file="src/main.rs", manager=mgr)
    assert name == "rust", (
        f"非 python 文件应路由到 rust server,实际返回 {name!r}。"
        "这是 Fix 2 要修复的硬编 bug。"
    )


def test_resolve_absolute_path_uses_extension():
    """绝对路径也靠扩展名路由。"""
    cfg = _make_config_two_servers()
    mgr = _make_manager(cfg)
    name = _resolve_lsp_server(file="/home/user/project/foo.rs", manager=mgr)
    assert name == "rust"


def test_resolve_unknown_extension_returns_none():
    """无 server 服务 .html → 返回 None(调用方可给出 clear error)。"""
    cfg = _make_config_two_servers()
    mgr = _make_manager(cfg)
    name = _resolve_lsp_server(file="index.html", manager=mgr)
    assert name is None


def test_resolve_no_servers_configured_returns_none():
    """空配置 → None。"""
    cfg = LspConfig.empty()
    mgr = _make_manager(cfg)
    name = _resolve_lsp_server(file="a.py", manager=mgr)
    assert name is None


def test_resolve_disabled_server_skipped():
    """disabled=True 的 server 不应被选中。"""
    cfg = LspConfig(
        version=1,
        servers={
            "python": LspServerConfig(
                command=("pyright-langserver", "--stdio"),
                filetypes=(".py",),
                disabled=True,  # disabled!
            ),
            "rust": LspServerConfig(
                command=("rust-analyzer",),
                filetypes=(".rs",),
            ),
        },
    )
    mgr = _make_manager(cfg)
    # .py → python 但 disabled
    name = _resolve_lsp_server(file="a.py", manager=mgr)
    assert name is None


def test_resolve_pyi_extension():
    """.pyi 文件也走 python server(多 filetype 支持)。"""
    cfg = _make_config_two_servers()
    mgr = _make_manager(cfg)
    name = _resolve_lsp_server(file="stubs.pyi", manager=mgr)
    assert name == "python"


# ── broker._execute 端到端路由测试 ───────────────────────────────────────────

class _FakeManager:
    """只记录 request_sync 的 server_name;不启动真实 server。"""

    def __init__(self, cfg: LspConfig) -> None:
        self.config = cfg
        self.calls: list[tuple[str, str]] = []  # [(server_name, method), ...]
        self._servers: dict = {}
        for name in cfg.servers:
            s = MagicMock()
            s.config = cfg.servers[name]
            self._servers[name] = s

    def server_status(self, server_name: str):
        return None  # Not configured = honest error

    def request_sync(self, server_name: str, method: str, params: dict, **kw) -> dict:
        self.calls.append((server_name, method))
        return {"result": []}

    def get_diagnostics(self, file: str):
        return None


def _make_broker_with_manager(fake_mgr: _FakeManager, tmp_path: Path):
    """构造一个 broker,把 lsp.get_manager() 和 workspace 注入。"""
    from argos.sandbox.broker import CapabilityBroker
    from argos.approval import ApprovalGate, ApprovalLevel

    gate = MagicMock()
    gate.level = ApprovalLevel.AUTO
    gate.request = MagicMock(return_value=True)

    broker = CapabilityBroker.__new__(CapabilityBroker)
    broker._gate = gate
    broker._workspace = tmp_path
    broker._registry = MagicMock()
    broker._registry.get.return_value = MagicMock(
        risk="low", reversible=True, egress_hosts=None, kind="tool", visibility="agent"
    )
    broker._event_bus = None
    return broker, fake_mgr


def test_broker_lsp_definition_routes_to_rust_server(tmp_path, monkeypatch):
    """lsp_definition 对 .rs 文件应路由 rust server,非硬编 python。"""
    cfg = _make_config_two_servers()
    fake_mgr = _FakeManager(cfg)

    # 创建 .rs 文件让 workspace 检查通过
    rs_file = tmp_path / "main.rs"
    rs_file.write_text("fn main() {}")

    import argos.lsp as _lsp_mod
    monkeypatch.setattr(_lsp_mod, "get_manager", lambda: fake_mgr)

    from argos.sandbox.broker import CapabilityBroker
    from argos.approval import ApprovalGate, ApprovalLevel

    gate = MagicMock()
    gate.level = ApprovalLevel.AUTO
    gate.request = MagicMock(return_value=True)

    broker = CapabilityBroker.__new__(CapabilityBroker)
    broker._gate = gate
    broker._workspace = tmp_path
    # registry.get 返回 cap.dispatch=None → 走内置 if/elif 路径(非 registry dispatch 路径)
    cap_mock = MagicMock()
    cap_mock.dispatch = None
    broker._registry = MagicMock()
    broker._registry.get.return_value = cap_mock
    broker._event_bus = None

    # 调 _execute,传 _gated=True 绕过 request() 管线(测试直接注入真实副作用层)
    result, _receipt = broker._execute(
        "lsp_definition",
        {"file": "main.rs", "line": 1, "col": 1},
        _gated=True,
    )

    # 路由应使用 "rust",不是 "python"
    # (calls 可能包含 _safe_sync_file 触发的 "__noop__" 前序调用,过滤掉它)
    real_calls = [(sn, m) for sn, m in fake_mgr.calls if sn != "__noop__"]
    assert real_calls, "manager.request_sync 应被调用(排除 __noop__ 辅助调用)"
    server_used = real_calls[0][0]
    assert server_used == "rust", (
        f"期望路由到 'rust' server,实际 {server_used!r}。"
        "Fix 2 目标:按扩展名路由,非硬编 python。"
    )


def test_broker_lsp_returns_error_for_unknown_extension(tmp_path, monkeypatch):
    """无对应 server 时,broker 应返回 clear error,不是 wrong-server 静默路由。"""
    cfg = _make_config_two_servers()
    fake_mgr = _FakeManager(cfg)

    html_file = tmp_path / "page.html"
    html_file.write_text("<html></html>")

    import argos.lsp as _lsp_mod
    monkeypatch.setattr(_lsp_mod, "get_manager", lambda: fake_mgr)

    from argos.sandbox.broker import CapabilityBroker
    from argos.approval import ApprovalLevel

    gate = MagicMock()
    gate.level = ApprovalLevel.AUTO
    gate.request = MagicMock(return_value=True)

    broker = CapabilityBroker.__new__(CapabilityBroker)
    broker._gate = gate
    broker._workspace = tmp_path
    cap_mock2 = MagicMock()
    cap_mock2.dispatch = None
    broker._registry = MagicMock()
    broker._registry.get.return_value = cap_mock2
    broker._event_bus = None

    result, _receipt = broker._execute(
        "lsp_definition",
        {"file": "page.html", "line": 1, "col": 1},
        _gated=True,
    )

    # 应是 JSON error,不应无声转到 python server
    assert fake_mgr.calls == [], "无对应 server 时不应路由到任何 server"
    parsed = json.loads(result)
    assert "error" in parsed, f"期望 error 字段,实际:\n{result}"
    assert "html" in parsed["error"].lower() or "no" in parsed["error"].lower() or \
           "server" in parsed["error"].lower()
