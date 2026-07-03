"""Internal documentation."""
from __future__ import annotations

from pathlib import Path

import pytest

from argos.tools import files


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


def test_search_files_by_name_glob_and_skips_heavy_dirs(ws):
    """Internal documentation."""
    (ws / "app.py").write_text("needle = 1\n")
    (ws / "readme.md").write_text("hi\n")
    (ws / ".git").mkdir()
    (ws / ".git" / "x.py").write_text("needle in git\n")
    out_f = files.search_files("*.py", target="files")
    assert "app.py" in out_f and "readme.md" not in out_f
    assert "x.py" not in out_f
    out_c = files.search_files("needle", target="content")
    assert "app.py" in out_c
    assert ".git" not in out_c


def test_search_files_skips_binary(ws):
    """Internal documentation."""
    (ws / "code.py").write_text("target_token\n")
    (ws / "blob.bin").write_bytes(b"\x00\x01target_token\xff\xfe")
    out = files.search_files("target_token", target="content")
    assert "code.py" in out
    assert "blob.bin" not in out


def test_read_file_offset_limit(ws):
    (ws / "lines.txt").write_text("a\nb\nc\nd\ne\n")
    r = files.read_file("lines.txt", offset=2, limit=2)
    head, _, body = r.partition("\n")
    assert "第 3" in head and ("-4" in head or "–4" in head)
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
    assert "3" in r


def test_read_empty_file_returns_empty_content(ws):
    (ws / "empty.txt").write_text("")
    r = files.read_file("empty.txt")
    assert "empty.txt" in r
    assert "越界" not in r
    assert "不存在" not in r


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
    big = "x" * 10000
    (ws / "big.txt").write_text(big)
    r2 = files.read_file("big.txt")
    assert len(r2) >= 10000


def test_edit_file_all_occurrences_true(tmp_path, monkeypatch):
    monkeypatch.setattr("argos.tools.files.WORKSPACE", tmp_path)
    (tmp_path / "a.py").write_text("x = 1\nx = 1\nx = 1\n")
    r = files.edit_file("a.py", "x = 1", "x = 2", all_occurrences=True)
    assert "3 处" in r
    assert (tmp_path / "a.py").read_text() == "x = 2\nx = 2\nx = 2\n"


def test_edit_file_all_occurrences_default_false_rejects_multi(tmp_path, monkeypatch):
    monkeypatch.setattr("argos.tools.files.WORKSPACE", tmp_path)
    (tmp_path / "a.py").write_text("x = 1\nx = 1\n")
    r = files.edit_file("a.py", "x = 1", "x = 2")
    assert "多次匹配" in r


def test_edit_file_all_occurrences_with_fuzzy_fallback(tmp_path, monkeypatch):
    monkeypatch.setattr("argos.tools.files.WORKSPACE", tmp_path)
    (tmp_path / "a.py").write_text("x   =   1\ny = 2\n")
    r = files.edit_file("a.py", "x = 1", "x = 9", all_occurrences=True)
    assert "1 处" in r
    assert "y = 2" in (tmp_path / "a.py").read_text()


def test_edit_file_all_occurrences_cap(tmp_path, monkeypatch):
    monkeypatch.setattr("argos.tools.files.WORKSPACE", tmp_path)
    content = "dup\n" * 1500
    (tmp_path / "a.py").write_text(content)
    r = files.edit_file("a.py", "dup", "x", all_occurrences=True)
    assert "匹配过多" in r
