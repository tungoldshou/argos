"""Internal documentation."""
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
    monkeypatch.setattr(shell, "_ws", lambda: tmp_path)
    return tmp_path


def test_network_denied_by_os_sandbox(ws):
    """Internal documentation."""
    (ws / "net.py").write_text(
        "import urllib.request\n"
        "urllib.request.urlopen('http://1.1.1.1', timeout=3)\n"
        "print('NETOK')\n"
    )
    out, code = shell.run_command("python3 net.py")
    assert "NETOK" not in out, "外联竟成功——网络没真关!"
    assert code not in (0, None)
    assert ("not permitted" in out) or ("Operation not permitted" in out) or ("URLError" in out)


def test_out_of_workspace_write_denied_by_os_sandbox(ws):
    """Internal documentation."""
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
    """Internal documentation."""
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
    """Internal documentation."""
    out, code = shell.run_command(
        "python3 -c \"import urllib.request;"
        " urllib.request.urlopen('http://1.1.1.1', timeout=3); print('NETOK')\""
    )
    assert "NETOK" not in out, "内联 eval 外联竟成功——网络没真关!"
    assert code is not None and code != 0, f"应真跑(非 arg 拒)且因网络被挡而非零: {out!r}"


def test_inline_eval_no_longer_name_rejected(ws):
    """Internal documentation."""
    out, code = shell.run_command("python3 -c \"print(6 * 7)\"")
    assert code == 0, out
    assert "42" in out
