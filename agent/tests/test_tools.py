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
