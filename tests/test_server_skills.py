"""Skills 端点测试 —— /skills 列表 + import/toggle 走闸。"""
import pytest
from fastapi.testclient import TestClient

from argos_agent import approval, server, skills


@pytest.fixture
def skills_dir_setup(tmp_path, monkeypatch):
    builtin = tmp_path / "builtin"
    builtin.mkdir()
    (builtin / "a.md").write_text(
        "---\nname: a\ndescription: alpha\ntrust: builtin\nenabled: true\n---\n# a\n", encoding="utf-8",
    )
    user = tmp_path / "user"
    user.mkdir()
    monkeypatch.setattr(skills, "BUILTIN_DIR", builtin)
    monkeypatch.setattr(skills, "USER_DIR", user)
    yield builtin, user


def test_get_skills_lists_all(skills_dir_setup, monkeypatch):
    client = TestClient(server.app)
    r = client.get("/skills")
    assert r.status_code == 200
    body = r.json()
    assert isinstance(body["skills"], list)
    assert any(s["name"] == "a" for s in body["skills"])


def test_toggle_calls_approval_then_persists(skills_dir_setup, monkeypatch):
    # 把 server._SKILL_GATE 替换成"自动批准"的 gate,然后断言 toggle 走通 + 写盘
    gate = approval.ApprovalGate(level=approval.ApprovalLevel.AUTO)
    monkeypatch.setattr(server, "_SKILL_GATE", gate)

    client = TestClient(server.app)
    r = client.post("/skills/a/toggle", json={"enabled": False})
    assert r.status_code == 200
    assert r.json().get("ok") is True
    a = next(s for s in skills.load_all() if s.name == "a")
    assert a.enabled is False


def test_toggle_deny_blocks(skills_dir_setup, monkeypatch):
    gate = approval.ApprovalGate(level=approval.ApprovalLevel.OBSERVE)
    monkeypatch.setattr(server, "_SKILL_GATE", gate)

    client = TestClient(server.app)
    r = client.post("/skills/a/toggle", json={"enabled": False})
    assert r.json().get("ok") is False
    a = next(s for s in skills.load_all() if s.name == "a")
    assert a.enabled is True  # 没动
