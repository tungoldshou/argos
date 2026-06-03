"""run_registry 测试 —— sqlite 持久,跨连接可查(模拟重启后恢复信源)。"""
import pytest

from argos_agent import run_registry


@pytest.fixture
def db(tmp_path, monkeypatch):
    monkeypatch.setattr(run_registry, "REGISTRY_PATH", tmp_path / "runs.db")
    return tmp_path


def test_open_then_get(db):
    run_registry.open_run(
        run_id="r1", session_id="s1", thread_id="t1",
        workspace="/ws", verify_dir="/vd", project_dir="/proj",
        project_mode=True, guard=["test_x.py"], goal="跑测试", verify_cmd="pytest",
    )
    rec = run_registry.get("r1")
    assert rec["status"] == "running"
    assert rec["project_mode"] is True
    assert rec["guard"] == ["test_x.py"]
    assert rec["verify_cmd"] == "pytest"


def test_mark_updates_status(db):
    run_registry.open_run(run_id="r2", session_id="s", thread_id="t", workspace="/w",
                          verify_dir="/v", project_dir="", project_mode=False,
                          guard=[], goal="g", verify_cmd=None)
    run_registry.mark("r2", "done")
    assert run_registry.get("r2")["status"] == "done"


def test_persists_across_connections(db):
    """每次操作新开 sqlite 连接 → 跨连接可读 = 跨重启可读。"""
    run_registry.open_run(run_id="r3", session_id="s", thread_id="t", workspace="/w",
                          verify_dir="/v", project_dir="", project_mode=False,
                          guard=[], goal="g", verify_cmd=None)
    assert run_registry.get("r3") is not None


def test_get_missing_returns_none(db):
    assert run_registry.get("nope") is None
