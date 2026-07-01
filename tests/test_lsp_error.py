"""LSP 工具错误路径(不需真 server,验 error JSON 形状)。"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from argos.lsp.config import LspConfig, LspServerConfig
from argos.lsp.manager import LspManager, set_spawn_proc_fn, set_event_emit_fn
from argos.lsp.tools import (
    lsp_definition_gated, lsp_diagnostics_gated,
    lsp_hover_gated, lsp_references_gated, lsp_document_symbols_gated,
    lsp_workspace_symbols_gated,
)


def test_disabled_server_returns_error_json(tmp_path):
    """config.disabled=True server → lsp_definition 返 error JSON,不抛。"""
    cfg = LspConfig(servers={
        "x": LspServerConfig(command=("y",), filetypes=(".py",), disabled=True),
    })
    m = LspManager(cfg)
    r = json.loads(lsp_definition_gated(
        server_name="x", file="a.py", line=1, col=1,
        manager=m, workspace=tmp_path,
    ))
    assert "error" in r
    assert "disabled" in r["error"]


def test_unknown_server_returns_error_json(tmp_path):
    """server_name 不存在 → lsp_definition 返 error JSON。"""
    cfg = LspConfig(servers={
        "python": LspServerConfig(command=("y",), filetypes=(".py",)),
    })
    m = LspManager(cfg)
    r = json.loads(lsp_definition_gated(
        server_name="nonexistent", file="a.py", line=1, col=1,
        manager=m, workspace=tmp_path,
    ))
    assert "error" in r
    assert "not configured" in r["error"]


def test_file_outside_workspace_returns_error(tmp_path):
    """workspace 牢笼外文件 → 工具返 `{"error": "file not in workspace"}`(spec §3)。"""
    cfg = LspConfig(servers={
        "python": LspServerConfig(command=("y",), filetypes=(".py",)),
    })
    m = LspManager(cfg)
    # 选 workspace = tmp_path,file 指向 /etc/passwd(workspace 之外)
    r = json.loads(lsp_definition_gated(
        server_name="python", file="/etc/passwd", line=1, col=1,
        manager=m, workspace=tmp_path,
    ))
    assert "error" in r
    assert "workspace" in r["error"] or "not in" in r["error"]


def test_diagnostics_for_disabled_server_returns_error(tmp_path):
    """disabled server 调 lsp_diagnostics → 返 error JSON(非抛)。"""
    cfg = LspConfig(servers={
        "x": LspServerConfig(command=("y",), filetypes=(".py",), disabled=True),
    })
    m = LspManager(cfg)
    r = json.loads(lsp_diagnostics_gated(
        server_name="x", file="a.py", manager=m, workspace=tmp_path,
    ))
    assert "error" in r


def test_all_six_gated_tools_dispatch_without_exception(tmp_path):
    """6 个 gated 工具都能被调(返 error JSON 也算 OK,关键不抛)。"""
    cfg = LspConfig(servers={
        "python": LspServerConfig(command=("y",), filetypes=(".py",), disabled=True),
    })
    m = LspManager(cfg)
    f = "a.py"
    for fn in [
        lambda: lsp_definition_gated(server_name="python", file=f, line=1, col=1, manager=m, workspace=tmp_path),
        lambda: lsp_references_gated(server_name="python", file=f, line=1, col=1, manager=m, workspace=tmp_path),
        lambda: lsp_hover_gated(server_name="python", file=f, line=1, col=1, manager=m, workspace=tmp_path),
        lambda: lsp_document_symbols_gated(server_name="python", file=f, manager=m, workspace=tmp_path),
        lambda: lsp_workspace_symbols_gated(server_name="python", query="foo", manager=m, workspace=tmp_path),
        lambda: lsp_diagnostics_gated(server_name="python", file=f, manager=m, workspace=tmp_path),
    ]:
        out = fn()
        d = json.loads(out)
        assert isinstance(d, dict)


def test_tools_registered_in_all_tool_names():
    """6 个 lsp_* 工具在 ALL_TOOL_NAMES 中;7 个 computer.* 在 ALL_TOOL_NAMES 中(工具数 22 → 29)。"""
    from argos.tools import ALL_TOOL_NAMES
    for name in ("lsp_definition", "lsp_references", "lsp_hover",
                 "lsp_document_symbols", "lsp_workspace_symbols", "lsp_diagnostics"):
        assert name in ALL_TOOL_NAMES
    for name in ("computer_screenshot", "computer_click", "computer_double_click",
                 "computer_type_text", "computer_key", "computer_scroll", "computer_open_app"):
        assert name in ALL_TOOL_NAMES
    assert len(ALL_TOOL_NAMES) == 31  # +propose_gui_verify(2d);宿主专属能力不计入


def test_tools_broker_dispatch_lsp_definition():
    """broker._execute 处理 action='lsp_*' 时派发到 LspManager(走 _execute 的 if 分支)。

    本测试只验 broker._RISK 包含 lsp_* + _execute 有 lsp_* 分支(代码静态断言,
    因为 _execute 走的是 action.startswith('lsp_') 分发,不在 _RISK 中也 OK)。"""
    from argos.sandbox import broker as broker_mod
    import inspect
    src = inspect.getsource(broker_mod.CapabilityBroker._execute)
    assert "lsp_" in src
    assert "lsp_definition" in src
    assert "lsp_diagnostics" in src
