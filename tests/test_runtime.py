"""运行时(项目模式)测试 —— 守住"在用户项目里干活 + 篡改可见"的关键能力。

懂技术用户的真实场景:agent 在我的项目里改代码、跑我的测试。沙盒隔离做不到了,
改用篡改可见:agent 动了测试文件,必须被检测到、警告用户。绝不静默放过。
"""
import pytest

from argos import runtime
from argos.tools import files


@pytest.fixture(autouse=True)
def reset_sandbox():
    # 每个测试后切回沙盒,避免污染其它测试的全局上下文。
    yield
    runtime.use_sandbox()


@pytest.fixture(autouse=True)
def auto_approve_gate():
    """装一个自动批准的审批 gate —— runtime 测试验证的是项目模式/路径逻辑,不是审批流。
    缺 gate 时有副作用工具会 fail-closed 默认拒绝,影响 write_file 等工具的正常测试。"""
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
    assert ctx.verify_dir == tmp_path.resolve()  # 验证就在项目里跑


def test_tools_write_into_user_project(tmp_path):
    runtime.use_project(str(tmp_path))
    files.write_file("app.py", "x=1")
    assert (tmp_path / "app.py").read_text() == "x=1"


def test_path_cage_still_holds_in_project_mode(tmp_path):
    # 即便在项目模式,也不能逃出项目根(防 agent 写到用户机器任意位置)。
    runtime.use_project(str(tmp_path))
    out = files.write_file("../../etc/evil", "x")
    assert "拒绝" in out


def test_tamper_detection_flags_modified_test(tmp_path):
    runtime.use_project(str(tmp_path))
    (tmp_path / "test_app.py").write_text("def test(): assert True\n")
    runtime.guard_files(["test_app.py"])
    # 没动 → 干净
    assert runtime.detect_tampering() == []
    # agent 改了测试 → 必须被检测到
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
    """旧 (mtime,size) 指纹能被 touch -r + 等长改写骗过;sha256 必须仍抓到。"""
    import os
    runtime.use_project(str(tmp_path))
    f = tmp_path / "test_a.py"
    f.write_text("assert aaa\n")          # 11 字节
    st0 = f.stat()
    runtime.guard_files(["test_a.py"])
    f.write_text("assert bbb\n")          # 同样 11 字节(骗过 size)
    os.utime(f, (st0.st_atime, st0.st_mtime))  # 复原 mtime(骗过 mtime)
    flagged = runtime.detect_tampering()
    assert any("test_a.py" in x for x in flagged)  # 内容变了 → sha256 抓到


def test_guard_project_tests_snapshots_existing_only(tmp_path):
    """头号护城河洞修复:project_mode 起 run 时自动快照【既有】测试文件。
    · 改/删既有测试 → detect_tampering 抓到(堵"偷改评判自己的测试骗过 verify");
    · 写【新】测试 → 不算篡改(TDD 合法,诚实协议自己鼓励先写测试);
    · 改源码(非测试)→ 不算篡改。
    覆盖测试发现模式 + 跳过 node_modules/.venv 等重目录。"""
    import time
    (tmp_path / "test_app.py").write_text("def test_a(): assert add(1, 1) == 2\n")
    (tmp_path / "src.py").write_text("def add(a, b): return a + b\n")
    sub = tmp_path / "pkg"; sub.mkdir()
    (sub / "feature_test.py").write_text("def test_b(): assert True\n")   # *_test.py 也算
    heavy = tmp_path / "node_modules" / "lib"; heavy.mkdir(parents=True)
    (heavy / "test_vendor.py").write_text("def test_v(): pass\n")          # 重目录里的不该被守

    runtime.use_project(str(tmp_path))
    n = runtime.guard_project_tests()
    assert n == 2, "只该守 test_app.py + pkg/feature_test.py(node_modules 跳过)"
    assert runtime.detect_tampering() == []

    # 改源码:不算篡改
    (tmp_path / "src.py").write_text("def add(a, b): return a + b  # tweak\n")
    assert runtime.detect_tampering() == []
    # 写新测试:不算篡改(TDD)
    (tmp_path / "test_new.py").write_text("def test_new(): pass\n")
    assert runtime.detect_tampering() == []
    # 改既有测试:必须被抓
    time.sleep(0.01)
    (tmp_path / "test_app.py").write_text("def test_a(): assert True  # 改弱\n")
    flagged = runtime.detect_tampering()
    assert any("test_app.py" in f for f in flagged)


def test_guard_project_tests_noop_in_sandbox_mode(tmp_path):
    """沙箱模式靠 verify_dir 隔离(agent 写不到),无需篡改快照 → guard_project_tests 返 0、不登记。"""
    runtime.use_sandbox()
    assert runtime.guard_project_tests() == 0


def test_guard_directory_flags_added_file(tmp_path):
    """守护整个测试目录:agent 偷偷新增 conftest.py(autouse fixture 中和断言)也算篡改。"""
    runtime.use_project(str(tmp_path))
    d = tmp_path / "tests"
    d.mkdir()
    (d / "test_a.py").write_text("def test(): assert True\n")
    runtime.guard_files(["tests"])
    assert runtime.detect_tampering() == []
    # 新增一个文件 → 必须被标"新增"
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
