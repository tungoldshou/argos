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
    assert "hello" in files.read_file("a.txt")


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


def test_read_file_offset_limit(ws):
    (ws / "lines.txt").write_text("a\nb\nc\nd\ne\n")
    r = files.read_file("lines.txt", offset=2, limit=2)
    # 第一行(行号提示)含 "第 3-4 行" 或 "第 3–4 行"(U+2013 连字符)
    head, _, body = r.partition("\n")
    assert "第 3" in head and ("-4" in head or "–4" in head)
    # 正文只含 c、d(从第 3 行起 2 行)
    assert "c" in body
    assert "d" in body
    assert "a" not in body
    assert "b" not in body
    assert "e" not in body


def test_read_file_offset_only(ws):
    (ws / "lines.txt").write_text("a\nb\nc\nd\ne\n")
    r = files.read_file("lines.txt", offset=3)
    assert "d" in r
    assert "e" in r
    assert "a" not in r


def test_read_file_offset_out_of_range(ws):
    (ws / "lines.txt").write_text("a\nb\nc\n")
    r = files.read_file("lines.txt", offset=100)
    assert "越界" in r
    assert "3" in r  # 总行数


def test_read_file_limit_zero(ws):
    (ws / "a.txt").write_text("x")
    r = files.read_file("a.txt", limit=0)
    assert "错误" in r
    assert "limit" in r


def test_read_file_default_unchanged(ws):
    (ws / "a.txt").write_text("hello\nworld\n")
    r = files.read_file("a.txt")
    assert "hello" in r
    assert "world" in r
    # 向后兼容:不再有 8000 字符硬截断
    big = "x" * 10000
    (ws / "big.txt").write_text(big)
    r2 = files.read_file("big.txt")
    assert len(r2) >= 10000  # 全文返回
