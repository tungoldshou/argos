import pytest

from argos import runtime
from argos.tools import files


@pytest.fixture(autouse=True)
def reset_sandbox():
    yield
    runtime.use_sandbox()


@pytest.fixture(autouse=True)
def auto_approve_gate():
    from argos import approval
    gate = approval.ApprovalGate(level=approval.ApprovalLevel.AUTO)
    token = approval.set_current_gate(gate)
    yield
    approval.reset_current_gate(token)


def test_use_project_switches_workspace(tmp_path):
    runtime.use_project(str(tmp_path))
    ctx = runtime.current()
    assert ctx.project_mode is True
    assert ctx.workspace == tmp_path.resolve()
    assert ctx.verify_dir == tmp_path.resolve()


def test_sandbox_defaults_follow_argos_config_dir(tmp_path, monkeypatch):
    monkeypatch.delenv("ARGOS_WORKSPACE", raising=False)
    monkeypatch.delenv("ARGOS_VERIFY_DIR", raising=False)
    config_dir = tmp_path / "cfg"
    monkeypatch.setenv("ARGOS_CONFIG_DIR", str(config_dir))

    runtime.use_sandbox()

    ctx = runtime.current()
    assert ctx.workspace == (config_dir / "workspace").resolve()
    assert ctx.verify_dir == (config_dir / "verify").resolve()


def test_file_tools_default_workspace_follows_argos_config_dir(tmp_path, monkeypatch):
    monkeypatch.delenv("ARGOS_WORKSPACE", raising=False)
    config_dir = tmp_path / "cfg"
    monkeypatch.setenv("ARGOS_CONFIG_DIR", str(config_dir))

    assert files._ws() == (config_dir / "workspace").resolve()


def test_tools_legacy_verify_dir_follows_argos_config_dir(tmp_path, monkeypatch):
    from argos import tools

    monkeypatch.delenv("ARGOS_VERIFY_DIR", raising=False)
    config_dir = tmp_path / "cfg"
    monkeypatch.setenv("ARGOS_CONFIG_DIR", str(config_dir))

    assert tools._vd() == (config_dir / "verify").resolve()


def test_tools_write_into_user_project(tmp_path):
    runtime.use_project(str(tmp_path))
    files.write_file("app.py", "x=1")
    assert (tmp_path / "app.py").read_text() == "x=1"


def test_path_cage_still_holds_in_project_mode(tmp_path):
    runtime.use_project(str(tmp_path))
    out = files.write_file("../../etc/evil", "x")
    assert "拒绝" in out


def test_tamper_detection_flags_modified_test(tmp_path):
    runtime.use_project(str(tmp_path))
    (tmp_path / "test_app.py").write_text("def test(): assert True\n")
    runtime.guard_files(["test_app.py"])
    assert runtime.detect_tampering() == []
    import time
    time.sleep(0.01)
    (tmp_path / "test_app.py").write_text("def test(): pass  # 偷偷改成永远过\n")
    flagged = runtime.detect_tampering()
    assert any("test_app.py" in f for f in flagged)


def test_tamper_detection_flags_deleted_test(tmp_path):
    runtime.use_project(str(tmp_path))
    (tmp_path / "test_x.py").write_text("assert True\n")
    runtime.guard_files(["test_x.py"])
    (tmp_path / "test_x.py").unlink()
    flagged = runtime.detect_tampering()
    assert any("test_x.py" in f and "删除" in f for f in flagged)


def test_tamper_detection_catches_same_size_same_mtime(tmp_path):
    import os
    runtime.use_project(str(tmp_path))
    f = tmp_path / "test_a.py"
    f.write_text("assert aaa\n")
    st0 = f.stat()
    runtime.guard_files(["test_a.py"])
    f.write_text("assert bbb\n")
    os.utime(f, (st0.st_atime, st0.st_mtime))
    flagged = runtime.detect_tampering()
    assert any("test_a.py" in x for x in flagged)


def test_guard_project_tests_snapshots_existing_only(tmp_path):
    import time
    (tmp_path / "test_app.py").write_text("def test_a(): assert add(1, 1) == 2\n")
    (tmp_path / "src.py").write_text("def add(a, b): return a + b\n")
    sub = tmp_path / "pkg"; sub.mkdir()
    (sub / "feature_test.py").write_text("def test_b(): assert True\n")
    heavy = tmp_path / "node_modules" / "lib"; heavy.mkdir(parents=True)
    (heavy / "test_vendor.py").write_text("def test_v(): pass\n")

    runtime.use_project(str(tmp_path))
    n = runtime.guard_project_tests()
    assert n == 2, "只该守 test_app.py + pkg/feature_test.py(node_modules 跳过)"
    assert runtime.detect_tampering() == []

    (tmp_path / "src.py").write_text("def add(a, b): return a + b  # tweak\n")
    assert runtime.detect_tampering() == []
    (tmp_path / "test_new.py").write_text("def test_new(): pass\n")
    assert runtime.detect_tampering() == []
    time.sleep(0.01)
    (tmp_path / "test_app.py").write_text("def test_a(): assert True  # 改弱\n")
    flagged = runtime.detect_tampering()
    assert any("test_app.py" in f for f in flagged)


def test_guard_project_tests_noop_in_sandbox_mode(tmp_path):
    runtime.use_sandbox()
    assert runtime.guard_project_tests() == 0


def test_guard_directory_flags_added_file(tmp_path):
    runtime.use_project(str(tmp_path))
    d = tmp_path / "tests"
    d.mkdir()
    (d / "test_a.py").write_text("def test(): assert True\n")
    runtime.guard_files(["tests"])
    assert runtime.detect_tampering() == []
    (d / "conftest.py").write_text("import pytest\n")
    flagged = runtime.detect_tampering()
    assert any("conftest.py" in f and "新增" in f for f in flagged)


def test_guard_directory_flags_modified_file(tmp_path):
    runtime.use_project(str(tmp_path))
    d = tmp_path / "tests"
    d.mkdir()
    (d / "test_a.py").write_text("def test(): assert True\n")
    runtime.guard_files(["tests"])
    (d / "test_a.py").write_text("def test(): pass\n")
    flagged = runtime.detect_tampering()
    assert any("test_a.py" in f and "被修改" in f for f in flagged)
