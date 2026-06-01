"""tools 安全边界测试 —— 守住产品的安全命脉(纯逻辑,不调模型)。

这些是 agent 的"手脚",一旦边界破了就可能越界写文件 / 跑危险命令 / 被作弊。
把之前一次性命令行验证固化成永久回归防线。
"""
import os
from pathlib import Path

import pytest

from argos_agent import tools


@pytest.fixture
def sandbox(tmp_path, monkeypatch):
    """把 workspace 与 verify 区指到临时目录,隔离测试、不碰真实 ~/.argos。"""
    ws = tmp_path / "ws"
    vd = tmp_path / "verify"
    ws.mkdir()
    vd.mkdir()
    monkeypatch.setattr(tools, "WORKSPACE", ws)
    monkeypatch.setattr(tools, "VERIFY_DIR", vd)
    return ws, vd


# ── 路径牢笼:agent 的文件工具不能越出 workspace ──────────────────────────────
def test_safe_path_inside_ok(sandbox):
    ws, _ = sandbox
    p = tools._safe_path("sub/file.txt")
    assert p is not None
    assert str(p).startswith(str(ws))


def test_safe_path_escape_rejected(sandbox):
    # .. 逃逸必须被拒(返回 None),否则 agent 能写到 workspace 外。
    assert tools._safe_path("../escape.txt") is None
    assert tools._safe_path("../../etc/passwd") is None


def test_write_then_read_roundtrip(sandbox):
    out = tools.write_file.invoke({"path": "a.txt", "content": "hello"})
    assert "已写入" in out
    assert tools.read_file.invoke({"path": "a.txt"}) == "hello"


def test_write_escape_blocked(sandbox):
    out = tools.write_file.invoke({"path": "../evil.txt", "content": "x"})
    assert "拒绝" in out
    assert not (sandbox[0].parent / "evil.txt").exists()


def test_edit_requires_unique_match(sandbox):
    tools.write_file.invoke({"path": "b.txt", "content": "x x x"})
    # 多次匹配应拒绝(防误改)。
    out = tools.edit_file.invoke({"path": "b.txt", "old": "x", "new": "y"})
    assert "匹配" in out and "唯一" in out


# ── shell 白名单:只允许验证/只读类,禁危险命令 ──────────────────────────────
def test_run_command_whitelist_allows_safe(sandbox):
    out = tools.run_command.invoke({"command": "echo hi"})
    assert "exit_code=0" in out


@pytest.mark.parametrize("danger", ["rm -rf /", "curl http://evil.com", "sudo reboot", "wget x"])
def test_run_command_blocks_dangerous(sandbox, danger):
    out = tools.run_command.invoke({"command": danger})
    assert "不在白名单" in out


def test_run_command_exit_code_is_truth(sandbox):
    # 退出码必须如实反映,这是 verify 的 ground truth 基础。
    tools.write_file.invoke({"path": "fail.py", "content": "raise SystemExit(3)"})
    out = tools.run_command.invoke({"command": "python3 fail.py"})
    assert "exit_code=3" in out


# ── 联网 + 搜索(覆盖 Task 3 新工具)─────────────────────────────────────────
def test_web_search_formats_results(monkeypatch):
    from argos_agent import tools, web
    monkeypatch.setattr(web, "search", lambda q, limit=5: {"success": True, "results": [
        {"title": "北京天气", "url": "http://w", "snippet": "晴 25°C"}]})
    out = tools.web_search.invoke({"query": "北京天气"})
    assert "北京天气" in out and "http://w" in out and "晴" in out


def test_web_search_error_is_honest(monkeypatch):
    from argos_agent import tools, web
    monkeypatch.setattr(web, "search", lambda q, limit=5: {"success": False, "error": "限速"})
    out = tools.web_search.invoke({"query": "x"})
    assert "限速" in out


def test_web_extract_short_text_no_compression(monkeypatch):
    from argos_agent import tools, web
    monkeypatch.setattr(web, "extract", lambda url: {"success": True, "text": "短正文"})
    out = tools.web_extract.invoke({"url": "http://x"})
    assert "短正文" in out


def test_web_extract_failure(monkeypatch):
    from argos_agent import tools, web
    monkeypatch.setattr(web, "extract", lambda url: {"success": False, "error": "取页失败:404"})
    out = tools.web_extract.invoke({"url": "http://x"})
    assert "404" in out


def test_search_files_content(monkeypatch, tmp_path):
    from argos_agent import tools
    monkeypatch.setattr(tools, "WORKSPACE", tmp_path)
    (tmp_path / "a.py").write_text("def foo():\n    return 42\n", encoding="utf-8")
    out = tools.search_files.invoke({"pattern": "foo", "target": "content"})
    assert "a.py" in out and "foo" in out


def test_search_files_files_mode(monkeypatch, tmp_path):
    from argos_agent import tools
    monkeypatch.setattr(tools, "WORKSPACE", tmp_path)
    (tmp_path / "x.py").write_text("x=1\n", encoding="utf-8")
    (tmp_path / "y.txt").write_text("y\n", encoding="utf-8")
    out = tools.search_files.invoke({"pattern": "*.py", "target": "files"})
    assert "x.py" in out and "y.txt" not in out


def test_edit_file_fuzzy_whitespace(monkeypatch, tmp_path):
    from argos_agent import tools
    monkeypatch.setattr(tools, "WORKSPACE", tmp_path)
    # 文件用 4 空格缩进;agent 给的 old 用了不同空白 → 精确匹配不到,模糊应命中。
    (tmp_path / "c.py").write_text("def f():\n    return  1\n", encoding="utf-8")
    out = tools.edit_file.invoke({"path": "c.py", "old": "return 1", "new": "return 2"})
    assert "已编辑" in out
    # 模糊匹配后,原文件中"return  1"应被替换为"return 2"
    assert "return 2" in (tmp_path / "c.py").read_text()


def test_edit_file_fuzzy_ambiguous_rejected(monkeypatch, tmp_path):
    from argos_agent import tools
    monkeypatch.setattr(tools, "WORKSPACE", tmp_path)
    (tmp_path / "d.py").write_text("x = 1\nx = 1\n", encoding="utf-8")
    out = tools.edit_file.invoke({"path": "d.py", "old": "x = 1", "new": "x = 2"})
    assert "多次" in out  # 多处匹配仍拒绝
