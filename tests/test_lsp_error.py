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
    cfg = LspConfig(servers={
        "python": LspServerConfig(command=("y",), filetypes=(".py",)),
    })
    m = LspManager(cfg)
    r = json.loads(lsp_definition_gated(
        server_name="python", file="/etc/passwd", line=1, col=1,
        manager=m, workspace=tmp_path,
    ))
    assert "error" in r
    assert "workspace" in r["error"] or "not in" in r["error"]


def test_diagnostics_for_disabled_server_returns_error(tmp_path):
    cfg = LspConfig(servers={
        "x": LspServerConfig(command=("y",), filetypes=(".py",), disabled=True),
    })
    m = LspManager(cfg)
    r = json.loads(lsp_diagnostics_gated(
        server_name="x", file="a.py", manager=m, workspace=tmp_path,
    ))
    assert "error" in r


def test_all_six_gated_tools_dispatch_without_exception(tmp_path):
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
    from argos.tools import ALL_TOOL_NAMES
    for name in ("lsp_definition", "lsp_references", "lsp_hover",
                 "lsp_document_symbols", "lsp_workspace_symbols", "lsp_diagnostics"):
        assert name in ALL_TOOL_NAMES
    for name in ("computer_screenshot", "computer_click", "computer_double_click",
                 "computer_type_text", "computer_key", "computer_scroll", "computer_open_app"):
        assert name in ALL_TOOL_NAMES
    assert len(ALL_TOOL_NAMES) == 31


def test_tools_broker_dispatch_lsp_definition():
    from argos.sandbox import broker as broker_mod
    import inspect
    src = inspect.getsource(broker_mod.CapabilityBroker._execute)
    assert "lsp_" in src
    assert "lsp_definition" in src
    assert "lsp_diagnostics" in src
