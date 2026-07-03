"""Internal documentation."""
from __future__ import annotations

import asyncio
import re
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from argos.lsp.client import LspClient
from argos.lsp.config import LspConfig, LspServerConfig
from argos.lsp.manager import (
    LspManager,
    _LSP_LOOP,
    _LSP_LOOP_THREAD,
    _LSP_STARTED,
    _ensure_lsp_loop_started,
    request_sync_via_loop,
    sync_file_sync,
)


# ── extract_file_writes ────────────────────────────────────────────


def test_extract_file_writes_single():
    """Internal documentation."""
    from argos.lsp.trigger import extract_file_writes
    code = "write_file('a.py', 'x = 1\\n')"
    writes = extract_file_writes(code)
    assert writes == [("a.py", "x = 1\n")]


def test_extract_file_writes_multiple():
    """Internal documentation."""
    from argos.lsp.trigger import extract_file_writes
    code = "write_file('a.py', '1')\nwrite_file('b.py', '2')"
    writes = extract_file_writes(code)
    assert writes == [("a.py", "1"), ("b.py", "2")]


def test_extract_file_writes_double_quotes():
    """Internal documentation."""
    from argos.lsp.trigger import extract_file_writes
    code = 'write_file("a.py", "hello\\nworld")'
    writes = extract_file_writes(code)
    assert writes == [("a.py", "hello\nworld")]


def test_extract_file_writes_no_call():
    """Internal documentation."""
    from argos.lsp.trigger import extract_file_writes
    assert extract_file_writes("x = 1\nprint(x)") == []
    assert extract_file_writes("") == []


def test_extract_file_writes_handles_escaped_quote():
    """Internal documentation."""
    from argos.lsp.trigger import extract_file_writes
    code = r"write_file('a.py', 'it\'s ok')"
    writes = extract_file_writes(code)
    assert writes and writes[0][0] == "a.py"


# ── extract_file_paths ─────────────────────────────────────────────


def test_extract_file_paths_combines_write_and_edit():
    """Internal documentation."""
    from argos.lsp.trigger import extract_file_paths
    code = (
        "write_file('a.py', '1')\n"
        "edit_file('a.py', 'old', 'new')\n"
        "edit_file('b.py', 'old', 'new')\n"
    )
    paths = extract_file_paths(code)
    assert "a.py" in paths
    assert "b.py" in paths
    assert paths.count("a.py") == 1


def test_extract_file_paths_no_call():
    """Internal documentation."""
    from argos.lsp.trigger import extract_file_paths
    assert extract_file_paths("print('hi')") == []




def test_lsp_loop_singleton():
    """Internal documentation."""
    import argos.lsp.manager as mgr_mod
    saved = (mgr_mod._LSP_LOOP, mgr_mod._LSP_LOOP_THREAD, mgr_mod._LSP_STARTED)
    try:
        mgr_mod._LSP_LOOP = None
        mgr_mod._LSP_LOOP_THREAD = None
        mgr_mod._LSP_STARTED = False
        mgr_mod._ensure_lsp_loop_started()
        assert mgr_mod._LSP_LOOP is not None
        assert mgr_mod._LSP_LOOP_THREAD is not None
        assert mgr_mod._LSP_STARTED is True
        loop1 = mgr_mod._LSP_LOOP
        mgr_mod._ensure_lsp_loop_started()
        assert mgr_mod._LSP_LOOP is loop1
    finally:
        mgr_mod._LSP_LOOP, mgr_mod._LSP_LOOP_THREAD, mgr_mod._LSP_STARTED = saved


def test_request_sync_via_loop_submits_to_background_loop():
    """Internal documentation."""
    import argos.lsp.manager as mgr_mod
    mgr_mod._ensure_lsp_loop_started()
    def coro_factory():
        async def _c():
            return 42
        return _c()
    result = mgr_mod.request_sync_via_loop(coro_factory, timeout=5.0)
    assert result == 42




def test_sync_file_sync_calls_sync_file_in_background_loop(tmp_path):
    """Internal documentation."""
    import argos.lsp.manager as mgr_mod

    cfg = LspConfig(servers={
        "python": LspServerConfig(command=("fake",), filetypes=(".py",)),
    })
    mgr = LspManager(cfg)
    called = {"n": 0, "args": None}

    async def fake_sync_file(self, path, content):
        called["n"] += 1
        called["args"] = (path, content)

    import unittest.mock
    with unittest.mock.patch.object(LspManager, "sync_file", fake_sync_file):
        mgr_mod.sync_file_sync(mgr, str(tmp_path / "a.py"), "x = 1\n", timeout=5.0)
    assert called["n"] == 1
    assert called["args"] == (str(tmp_path / "a.py"), "x = 1\n")


def test_sync_file_sync_handles_noop_silently(tmp_path):
    """Internal documentation."""
    import argos.lsp.manager as mgr_mod

    cfg = LspConfig(servers={
        "python": LspServerConfig(command=("fake",), filetypes=(".py",)),
    })
    mgr = LspManager(cfg)

    async def boom(self, path, content):
        raise RuntimeError("simulated LSP failure")

    import unittest.mock
    with unittest.mock.patch.object(LspManager, "sync_file", boom):
        mgr_mod.sync_file_sync(mgr, str(tmp_path / "a.py"), "x", timeout=2.0)
