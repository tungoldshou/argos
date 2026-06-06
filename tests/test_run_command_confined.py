"""C1 铁证:run_command 的 host 子进程被关进 Seatbelt(网络 OFF + 写牢笼 workspace)。

安全不变量(spec §6.2/§6.3):run_command 不再是无约束的 host 外泄原语。
  · 网络外泄不可能 —— deny network*(OS 级,不是 arg-inspection)。
  · 越界写被挡 —— file-write* 仅 workspace+temp。
  · 正常 in-workspace 命令仍能跑(pytest/python/ls/构建无需网络)。
另:防御纵深 —— python/node 内联 eval(-c/-e)与 npx 任意包执行被 arg-inspection 拒;
   run_command 风险升 high,AUTO 档也强制确认(永不静默执行 shell)。
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

from argos_agent.tools import shell

pytestmark = pytest.mark.skipif(sys.platform != "darwin", reason="Seatbelt 仅 macOS")


@pytest.fixture
def ws(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("ARGOS_WORKSPACE", str(tmp_path))
    # files._ws() 读 runtime 或模块级 WORKSPACE;模块级在 import 时已固化,
    # 用 monkeypatch 直接把 shell 依赖的 _ws 指向 tmp_path 最稳。
    monkeypatch.setattr(shell, "_ws", lambda: tmp_path)
    return tmp_path


def test_network_denied_by_os_sandbox(ws):
    """(a) 经 run_command 跑一个 workspace 内脚本试图外联 → 被 OS 沙箱挡(非 arg-inspection)。"""
    (ws / "net.py").write_text(
        "import urllib.request\n"
        "urllib.request.urlopen('http://1.1.1.1', timeout=3)\n"
        "print('NETOK')\n"
    )
    out, code = shell.run_command("python3 net.py")
    assert "NETOK" not in out, "外联竟成功——网络没真关!"
    # OS 拒绝表现为非零退出 + 权限/连接错误(不是白名单/arg 拒绝串)。
    assert code not in (0, None)
    assert ("not permitted" in out) or ("Operation not permitted" in out) or ("URLError" in out)


def test_out_of_workspace_write_denied_by_os_sandbox(ws):
    """(b) 经 run_command 跑脚本试图写 home → 被 OS 沙箱挡,逃逸文件不存在。"""
    escape = Path.home() / ".argos_c1_test_escape"
    if escape.exists():
        escape.unlink()
    (ws / "wr.py").write_text(
        "import pathlib\n"
        "pathlib.Path.home().joinpath('.argos_c1_test_escape').write_text('x')\n"
        "print('WROTE')\n"
    )
    out, code = shell.run_command("python3 wr.py")
    assert "WROTE" not in out, "越界写竟成功——OS 沙箱没生效!"
    assert escape.exists() is False
    assert ("not permitted" in out) or ("PermissionError" in out)


def test_in_workspace_command_still_works(ws):
    """(c) 正常 in-workspace 命令(写 workspace 内文件)仍成功 —— 沙箱不误伤合法活。"""
    (ws / "good.py").write_text(
        "import pathlib\n"
        "pathlib.Path('good_out.txt').write_text('done')\n"
        "print('OKWORKS')\n"
    )
    out, code = shell.run_command("python3 good.py")
    assert code == 0, out
    assert "OKWORKS" in out
    assert (ws / "good_out.txt").read_text() == "done"


def test_ls_in_workspace_works(ws):
    (ws / "marker.txt").write_text("hi")
    out, code = shell.run_command("ls")
    assert code == 0
    assert "marker.txt" in out


def test_python_inline_eval_rejected(ws):
    """防御纵深:python3 -c 内联 eval 被 arg-inspection 拒(不进沙箱执行)。"""
    out, code = shell.run_command(
        "python3 -c \"import urllib.request; urllib.request.urlopen('http://evil/')\""
    )
    assert code is None  # arg 校验失败 → exit_code=None
    assert "内联" in out or "-c" in out


def test_node_inline_eval_rejected(ws):
    out, code = shell.run_command("node -e \"require('http')\"")
    assert code is None
    assert "内联" in out or "-e" in out


def test_python_stdin_rejected(ws):
    out, code = shell.run_command("python3 -")
    assert code is None
    assert "stdin" in out or "内联" in out or "-" in out


def test_npx_arbitrary_package_rejected(ws):
    out, code = shell.run_command("npx some-arbitrary-pkg")
    assert code is None
    assert "npx" in out
