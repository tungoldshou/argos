"""Skills 仓库测试 —— 文件系统操作,无网络。"""
import pytest
from pathlib import Path

from argos_agent import skills


@pytest.fixture
def skills_dir(tmp_path, monkeypatch):
    builtin = tmp_path / "builtin"
    builtin.mkdir()
    (builtin / "a.md").write_text(
        "---\nname: a\ndescription: alpha\ntrust: builtin\nenabled: true\n---\n# a\n", encoding="utf-8",
    )
    (builtin / "b.md").write_text(
        "---\nname: b\ndescription: bravo\ntrust: builtin\nenabled: false\n---\n# b\n", encoding="utf-8",
    )
    user = tmp_path / "user"
    user.mkdir()
    (user / "c.md").write_text(
        "---\nname: c\ndescription: charlie\ntrust: imported\nenabled: true\nsource: https://example.com/c\n---\n# c\n", encoding="utf-8",
    )
    monkeypatch.setattr(skills, "BUILTIN_DIR", builtin)
    monkeypatch.setattr(skills, "USER_DIR", user)
    yield builtin, user


def test_load_all_merges_dirs(skills_dir):
    all_ = skills.load_all()
    names = {s.name for s in all_}
    assert names == {"a", "b", "c"}
    # user 同名覆盖 builtin
    a = next(s for s in all_ if s.name == "a")
    assert a.trust == "builtin"


def test_toggle_persists(skills_dir):
    _, user = skills_dir
    skills.toggle("a", enabled=False)
    p = next(skills_dir[0].glob("a.md"))
    text = p.read_text(encoding="utf-8")
    assert "enabled: false" in text


def test_import_writes_to_user_dir(tmp_path, skills_dir, monkeypatch):
    _, user = skills_dir
    content = "---\nname: x\ndescription: x desc\ntrust: imported\nenabled: true\n---\n# x\n"
    out = skills.import_skill(content=content, source="inline")
    assert (user / "x.md").exists()
    assert "inline" in out.source  # source 记录下来


def test_import_rejects_oversize(tmp_path, skills_dir):
    huge = "---\nname: big\ndescription: d\ntrust: imported\nenabled: true\n---\n" + ("x" * 4000)
    with pytest.raises(ValueError, match="3000"):
        skills.import_skill(content=huge, source="inline")
