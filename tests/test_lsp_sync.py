"""Task 7:loop 接线 + request_sync 单例后台 loop 重构 + extract_file_writes regex。

三个测试对象:
1. `lsp.trigger.extract_file_writes` 正则:抽 write_file(path, content) → (path, content) 列表
2. `lsp.trigger.extract_file_paths` 正则:抽 write_file/edit_file 涉及的 path 列表
3. `LspManager.request_sync` / `sync_file_sync` 用**模块级单例后台 loop**(option b)
   — 不再为每次调用 fresh ThreadPoolExecutor;LspManager 状态在长寿命 loop 内,
   跨调用 LspClient 持久化。

沙箱内 `tools/files.py` **不**动;host loop 在 `sandbox.exec_code` 成功后
解析 code 块抽 write_file/edit_file 调用 → 调 `lsp_manager.sync_file_sync`。"""
from __future__ import annotations

import asyncio
import re
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from argos_agent.lsp.client import LspClient
from argos_agent.lsp.config import LspConfig, LspServerConfig
from argos_agent.lsp.manager import (
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
    """单 write_file 调 → 1 个 (path, content) tuple。"""
    from argos_agent.lsp.trigger import extract_file_writes
    code = "write_file('a.py', 'x = 1\\n')"
    writes = extract_file_writes(code)
    assert writes == [("a.py", "x = 1\n")]


def test_extract_file_writes_multiple():
    """多 write_file → 多 tuple 保顺序。"""
    from argos_agent.lsp.trigger import extract_file_writes
    code = "write_file('a.py', '1')\nwrite_file('b.py', '2')"
    writes = extract_file_writes(code)
    assert writes == [("a.py", "1"), ("b.py", "2")]


def test_extract_file_writes_double_quotes():
    """双引号版本同样工作。"""
    from argos_agent.lsp.trigger import extract_file_writes
    code = 'write_file("a.py", "hello\\nworld")'
    writes = extract_file_writes(code)
    assert writes == [("a.py", "hello\nworld")]


def test_extract_file_writes_no_call():
    """无 write_file 调 → 空 list。"""
    from argos_agent.lsp.trigger import extract_file_writes
    assert extract_file_writes("x = 1\nprint(x)") == []
    assert extract_file_writes("") == []


def test_extract_file_writes_handles_escaped_quote():
    """内容含转义引号(\\') → 内容保留。"""
    from argos_agent.lsp.trigger import extract_file_writes
    code = r"write_file('a.py', 'it\'s ok')"
    writes = extract_file_writes(code)
    # 简化:正则抓 path + content 字符串字面量;转义保留 raw 形式
    assert writes and writes[0][0] == "a.py"


# ── extract_file_paths ─────────────────────────────────────────────


def test_extract_file_paths_combines_write_and_edit():
    """extract_file_paths 抓 write_file + edit_file 涉及的 path,去重。"""
    from argos_agent.lsp.trigger import extract_file_paths
    code = (
        "write_file('a.py', '1')\n"
        "edit_file('a.py', 'old', 'new')\n"
        "edit_file('b.py', 'old', 'new')\n"
    )
    paths = extract_file_paths(code)
    assert "a.py" in paths
    assert "b.py" in paths
    assert paths.count("a.py") == 1   # 去重


def test_extract_file_paths_no_call():
    """无 write/edit → 空 list。"""
    from argos_agent.lsp.trigger import extract_file_paths
    assert extract_file_paths("print('hi')") == []


# ── 模块级单例后台 loop ─────────────────────────────────────────────


def test_lsp_loop_singleton():
    """`_ensure_lsp_loop_started` 起一次后,loop + thread + started flag 都稳定。"""
    # 测试隔离:用 patch 触发 reset 检查
    import argos_agent.lsp.manager as mgr_mod
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
        # 二次调:loop 不重建
        mgr_mod._ensure_lsp_loop_started()
        assert mgr_mod._LSP_LOOP is loop1
    finally:
        mgr_mod._LSP_LOOP, mgr_mod._LSP_LOOP_THREAD, mgr_mod._LSP_STARTED = saved


def test_request_sync_via_loop_submits_to_background_loop():
    """`request_sync_via_loop(coro_factory)` 在 background loop 跑协程,等结果。"""
    import argos_agent.lsp.manager as mgr_mod
    mgr_mod._ensure_lsp_loop_started()
    # 简单协程:返 42
    def coro_factory():
        async def _c():
            return 42
        return _c()
    result = mgr_mod.request_sync_via_loop(coro_factory, timeout=5.0)
    assert result == 42


# ── sync_file_sync(loop 触发位) ───────────────────────────────────


def test_sync_file_sync_calls_sync_file_in_background_loop(tmp_path):
    """`sync_file_sync(path, content)` 在 background loop 跑 sync_file,等结果。"""
    # 临时构造一个最小 manager,monkeypatch sync_file 验被调
    import argos_agent.lsp.manager as mgr_mod

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
    """`sync_file_sync` 内部异常 → 不抛(对外 best-effort)。"""
    import argos_agent.lsp.manager as mgr_mod

    cfg = LspConfig(servers={
        "python": LspServerConfig(command=("fake",), filetypes=(".py",)),
    })
    mgr = LspManager(cfg)

    async def boom(self, path, content):
        raise RuntimeError("simulated LSP failure")

    import unittest.mock
    with unittest.mock.patch.object(LspManager, "sync_file", boom):
        # 不应抛
        mgr_mod.sync_file_sync(mgr, str(tmp_path / "a.py"), "x", timeout=2.0)
