"""运行时(项目模式)测试 —— 守住"在用户项目里干活 + 篡改可见"的关键能力。

懂技术用户的真实场景:agent 在我的项目里改代码、跑我的测试。沙盒隔离做不到了,
改用篡改可见:agent 动了测试文件,必须被检测到、警告用户。绝不静默放过。
"""
import pytest

from argos_agent import runtime, tools


@pytest.fixture(autouse=True)
def reset_sandbox():
    # 每个测试后切回沙盒,避免污染其它测试的全局上下文。
    yield
    runtime.use_sandbox()


def test_use_project_switches_workspace(tmp_path):
    runtime.use_project(str(tmp_path))
    ctx = runtime.current()
    assert ctx.project_mode is True
    assert ctx.workspace == tmp_path.resolve()
    assert ctx.verify_dir == tmp_path.resolve()  # 验证就在项目里跑


def test_tools_write_into_user_project(tmp_path):
    runtime.use_project(str(tmp_path))
    tools.write_file.invoke({"path": "app.py", "content": "x=1"})
    assert (tmp_path / "app.py").read_text() == "x=1"


def test_path_cage_still_holds_in_project_mode(tmp_path):
    # 即便在项目模式,也不能逃出项目根(防 agent 写到用户机器任意位置)。
    runtime.use_project(str(tmp_path))
    out = tools.write_file.invoke({"path": "../../etc/evil", "content": "x"})
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
