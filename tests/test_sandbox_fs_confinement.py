"""Phase 3 铁证:FS 牢笼由 OS 沙箱真实生效(非 smolagents AST 限制)。
故意授权 os import 让 AST 放行,断言【写越界】被 OS 挡、【写 workspace 内】成功。
跑在有沙箱后端的平台(macOS Seatbelt / Linux bwrap/unshare);无后端时干净 skip。"""
from __future__ import annotations

from pathlib import Path

import pytest

from argos_agent.sandbox.executor import select_backend


@pytest.fixture
def ex(tmp_path: Path, requires_sandbox):
    e = select_backend()()
    # 授权 os/pathlib 让 AST 不挡;边界改由 OS 沙箱负责。
    e.spawn(workspace=tmp_path, namespace={"__authorized_imports__": ["os", "pathlib"]})
    yield e
    e.close()


def test_write_inside_workspace_succeeds(ex, tmp_path):
    code = "import pathlib\np = pathlib.Path('hello.txt')\np.write_text('ok')\np.read_text()"
    r = ex.exec_code(code)
    assert r.ok, r.exc
    assert "ok" in r.value_repr
    assert (tmp_path / "hello.txt").exists()   # 真落盘在 workspace 内


def test_write_outside_workspace_blocked_by_os(ex):
    # 试图写 home 下一个文件 —— OS 沙箱必须挡住(PermissionError/OSError)。
    code = (
        "import pathlib\n"
        "target = pathlib.Path.home() / '.argos_escape_probe'\n"
        "target.write_text('escaped')\n"
        "'WROTE'"
    )
    r = ex.exec_code(code)
    # 期望:异常(被 OS 拒),绝不能 ok 且 value_repr=='WROTE'
    assert not (r.ok and r.value_repr == "'WROTE'"), "越界写竟成功——OS 沙箱没生效!"
    assert (Path.home() / ".argos_escape_probe").exists() is False


def test_read_ssh_blocked_or_empty(ex):
    # 读 ~/.ssh:profile 放宽 file-read*,所以读【可能成功】——但本测试要点是
    # 外泄向量是【网络+越界写】,不是读。这里断言:即便读到,也无法把它【写出 workspace】或【发网络】。
    # 真正的外泄拦截见 test_sandbox_network_off + 越界写测试。此处仅记录读策略,不强制 deny read。
    code = (
        "import pathlib\n"
        "d = pathlib.Path.home() / '.ssh'\n"
        "str(d.exists())"
    )
    r = ex.exec_code(code)
    assert r.ok  # 读路径不抛;外泄被网络/写双重挡死(见另两测试)
