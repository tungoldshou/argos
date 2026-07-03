"""Internal documentation."""
from __future__ import annotations

from pathlib import Path

import pytest

from argos.sandbox.executor import select_backend


@pytest.fixture
def ex(tmp_path: Path, requires_sandbox):
    e = select_backend()()
    e.spawn(workspace=tmp_path, namespace={"__authorized_imports__": ["os", "pathlib"]})
    yield e
    e.close()


def test_write_inside_workspace_succeeds(ex, tmp_path):
    code = "import pathlib\np = pathlib.Path('hello.txt')\np.write_text('ok')\np.read_text()"
    r = ex.exec_code(code)
    assert r.ok, r.exc
    assert "ok" in r.value_repr
    assert (tmp_path / "hello.txt").exists()


def test_write_outside_workspace_blocked_by_os(ex):
    code = (
        "import pathlib\n"
        "target = pathlib.Path.home() / '.argos_escape_probe'\n"
        "target.write_text('escaped')\n"
        "'WROTE'"
    )
    r = ex.exec_code(code)
    assert not (r.ok and r.value_repr == "'WROTE'"), "越界写竟成功——OS 沙箱没生效!"
    assert (Path.home() / ".argos_escape_probe").exists() is False


def test_read_credentials_now_blocked(ex):
    """Internal documentation."""
    import sys
    if sys.platform != "darwin":
        pytest.skip("此用例只验证 Seatbelt EPERM 语义;bwrap 凭据遮蔽由 Linux 后端测试覆盖")
    code = (
        "import pathlib\n"
        "str((pathlib.Path.home() / '.ssh').exists())"
    )
    r = ex.exec_code(code)
    assert not r.ok, "凭据目录读/stat 应被 OS 拒(Phase 0 收紧)"
    assert "Operation not permitted" in (r.exc or "") or "Permission" in (r.exc or ""), r.exc
