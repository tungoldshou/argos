"""Phase 3:纯沙箱 file 工具(裸函数,无 LangChain/审批装饰)。
工作目录由 ARGOS_WORKSPACE 环境/_ws() 决定;测试用 tmp workspace。"""
from __future__ import annotations

from pathlib import Path

import pytest

from argos_agent.tools import files


@pytest.fixture
def ws(tmp_path, monkeypatch):
    monkeypatch.setattr(files, "WORKSPACE", tmp_path.resolve())
    return tmp_path


def test_write_then_read(ws):
    assert "已写入" in files.write_file("a.txt", "hello")
    assert files.read_file("a.txt") == "hello"


def test_read_missing(ws):
    assert "不存在" in files.read_file("nope.txt")


def test_path_escape_denied(ws):
    assert "越出" in files.write_file("../escape.txt", "x")
    assert "越出" in files.read_file("../../etc/passwd")


def test_edit_exact_unique(ws):
    files.write_file("b.py", "x = 1\ny = 2\n")
    assert "已编辑" in files.edit_file("b.py", "x = 1", "x = 99")
    assert "x = 99" in files.read_file("b.py")


def test_edit_ambiguous(ws):
    files.write_file("c.txt", "dup\ndup\n")
    assert "多次匹配" in files.edit_file("c.txt", "dup", "x")


def test_search_files_content(ws):
    files.write_file("d.py", "def foo():\n    return 1\n")
    out = files.search_files("foo", target="content")
    assert "d.py" in out and "foo" in out
