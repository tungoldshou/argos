"""C1 铁证:run_command 的 host 子进程被关进 Seatbelt(网络 OFF + 写牢笼 workspace)。

安全不变量(spec §6.2/§6.3):run_command 不再是无约束的 host 外泄原语。
  · 网络外泄不可能 —— deny network*(OS 级,不是 arg-inspection)。
  · 越界写被挡 —— file-write* 仅 workspace+temp。
  · 正常 in-workspace 命令仍能跑(pytest/python/ls/构建无需网络)。
2026-06-20 重设:run_command 不再有命令名白名单 / arg-inspection 拒绝(Codex/Claude Code 模型)——
   边界是 OS 沙箱,任意命令(含 python -c / npx)都能跑,但外联被沙箱挡、越界写被挡、危险命令由
   评估器 hard rule 在审批层先拦。
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

from argos.tools import shell

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


def test_python_inline_eval_runs_but_network_contained(ws):
    """2026-06-20 重设:python3 -c 内联 eval 不再被名字/arg 拒,直接在牢笼里跑 —— 真边界是 OS 沙箱:
    内联代码试图外联仍被 deny network* 挡死。区别于旧行为(arg 拒 → code=None);现在真执行(code!=None)。"""
    out, code = shell.run_command(
        "python3 -c \"import urllib.request;"
        " urllib.request.urlopen('http://1.1.1.1', timeout=3); print('NETOK')\""
    )
    assert "NETOK" not in out, "内联 eval 外联竟成功——网络没真关!"
    assert code is not None and code != 0, f"应真跑(非 arg 拒)且因网络被挡而非零: {out!r}"


def test_inline_eval_no_longer_name_rejected(ws):
    """旧防御纵深(python -c / node -e / npx 任意包 → arg 拒)已移除:边界改由 OS 沙箱承担。
    用一条纯本地 python -c(无网络、无越界写)验证它真在牢笼里跑通,而非被名字拒。"""
    out, code = shell.run_command("python3 -c \"print(6 * 7)\"")
    assert code == 0, out
    assert "42" in out
