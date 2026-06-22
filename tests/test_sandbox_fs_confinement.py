"""Phase 3 铁证:FS 牢笼由 OS 沙箱真实生效(非 smolagents AST 限制)。
故意授权 os import 让 AST 放行,断言【写越界】被 OS 挡、【写 workspace 内】成功。
跑在有沙箱后端的平台(macOS Seatbelt / Linux bwrap/unshare);无后端时干净 skip。"""
from __future__ import annotations

from pathlib import Path

import pytest

from argos.sandbox.executor import select_backend


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


def test_read_credentials_now_blocked(ex):
    """Phase 0(2026-06-20):凭据目录读已被 Seatbelt deny —— 对 ~/.ssh 做 stat/read 抛 PermissionError。
    此前 file-read* 全盘放宽(读 ~/.ssh 可成,是当初诚实记录的局限);开"出网阀"前先堵读侧
    (能读 ~/.ssh 就已 game over)。外泄仍由网络 OFF + 写牢笼双重挡(见另两测试),读侧再加这层。

    平台局限(诚实标注,2026-06-22):读侧 deny 是 Seatbelt 专属。Linux bwrap 按设计 `--ro-bind / /`
    放宽读(让模型能 import 库 / 读项目源码),且对 namespace 内 mapped-root 无法用挂载手段让 stat
    抛 EPERM —— 故此断言仅在 macOS/Seatbelt 成立。Linux 上凭据【外泄】仍被网络 OFF + 写牢笼挡死
    (上两测试覆盖);读侧硬化(tmpfs 遮蔽 ~/.ssh 等)列为后续。不在 bwrap 上假装有这层。"""
    import sys
    if sys.platform != "darwin":
        pytest.skip("凭据读 deny 是 Seatbelt 专属;bwrap 按设计放宽读,外泄仍由网络 OFF + 写牢笼挡(见上两测试)")
    code = (
        "import pathlib\n"
        "str((pathlib.Path.home() / '.ssh').exists())"
    )
    r = ex.exec_code(code)
    assert not r.ok, "凭据目录读/stat 应被 OS 拒(Phase 0 收紧)"
    assert "Operation not permitted" in (r.exc or "") or "Permission" in (r.exc or ""), r.exc
