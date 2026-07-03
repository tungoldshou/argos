import pytest
from pathlib import Path

from argos import skills


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
    a = next(s for s in all_ if s.name == "a")
    assert a.trust == "builtin"


def test_user_dir_honors_argos_config_dir(tmp_path, monkeypatch):
    cfg_dir = tmp_path / ".argos"
    user = cfg_dir / "skills"
    user.mkdir(parents=True)
    (user / "x.md").write_text(
        "---\nname: x\ndescription: xray\ntrust: user_created\nenabled: true\n---\n# x\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("ARGOS_CONFIG_DIR", str(cfg_dir))
    monkeypatch.setattr(skills, "BUILTIN_DIR", tmp_path / "builtin")
    monkeypatch.setattr(skills, "USER_DIR", None)

    assert "x" in {s.name for s in skills.load_all()}


def test_toggle_persists(skills_dir):
    _, user = skills_dir
    skills.toggle("a", enabled=False)
    p = next(skills_dir[0].glob("a.md"))
    text = p.read_text(encoding="utf-8")
    assert "enabled: false" in text


def test_load_all_finds_subdir_skill(skills_dir):
    _, user = skills_dir
    sub = user / "promoted-skill"
    sub.mkdir()
    (sub / "SKILL.md").write_text(
        "---\nname: promoted-skill\ndescription: subdir one\n"
        "trust: user_created\nenabled: true\n---\n# promoted\n",
        encoding="utf-8",
    )
    names = {s.name for s in skills.load_all()}
    assert "promoted-skill" in names, "子目录 <name>/SKILL.md 晋升技能必须被 load_all 扫到"
    assert {"a", "b", "c"} <= names


def test_load_all_subdir_does_not_override_flat(skills_dir):
    _, user = skills_dir
    sub = user / "c"
    sub.mkdir()
    (sub / "SKILL.md").write_text(
        "---\nname: c\ndescription: SUBDIR_VERSION\ntrust: user_created\nenabled: true\n---\n# c2\n",
        encoding="utf-8",
    )
    c = next(s for s in skills.load_all() if s.name == "c")
    assert c.description == "charlie", "同名平铺技能先到,子目录版不覆盖"


def test_toggle_subdir_skill(skills_dir):
    _, user = skills_dir
    sub = user / "promoted-skill"
    sub.mkdir()
    md = sub / "SKILL.md"
    md.write_text(
        "---\nname: promoted-skill\ndescription: subdir one\n"
        "trust: user_created\nenabled: true\n---\n# promoted\n",
        encoding="utf-8",
    )
    assert skills.toggle("promoted-skill", enabled=False) is True
    assert "enabled: false" in md.read_text(encoding="utf-8")


def test_import_writes_to_user_dir(tmp_path, skills_dir, monkeypatch):
    _, user = skills_dir
    content = "---\nname: x\ndescription: x desc\ntrust: imported\nenabled: true\n---\n# x\n"
    out = skills.import_skill(content=content, source="inline")
    assert (user / "x.md").exists()
    assert "inline" in out.source


def test_import_rejects_oversize(tmp_path, skills_dir):
    huge = "---\nname: big\ndescription: d\ntrust: imported\nenabled: true\n---\n" + ("x" * 4000)
    with pytest.raises(ValueError, match="3000"):
        skills.import_skill(content=huge, source="inline")



class _FakeEmbedder:
    dim = 8

    def __init__(self, fn):
        self._fn = fn

    def embed(self, texts):
        return self._fn(texts)


def _use_embedder(monkeypatch, fn):
    monkeypatch.setattr("argos.config.active_embedder", lambda: _FakeEmbedder(fn))


def test_recall_keyword_fallback_when_no_embedder(skills_dir, monkeypatch):
    monkeypatch.setattr("argos.config.active_embedder", lambda: None)
    # skills_dir: a(desc=alpha,enabled) / b(disabled) / c(desc=charlie,enabled)
    out = skills.recall("帮我处理 alpha 相关的事", k=3, sim_min=0.4)
    assert "a" in {s.name for s in out}, "goal 含 'alpha' → 关键词命中 skill a 的描述"
    assert "b" not in {s.name for s in out}, "disabled skill 不召回"
    assert skills.recall("zzz totally unrelated", k=3) == []


def test_recall_returns_top_k_enabled_by_cosine(monkeypatch, tmp_path):
    builtin = tmp_path / "b"
    user = tmp_path / "u"
    builtin.mkdir()
    user.mkdir()
    (builtin / "py-test-runner.md").write_text(
        "---\nname: py-test-runner\ndescription: d\ntrust: builtin\nenabled: true\n---\n# p\n", encoding="utf-8",
    )
    (builtin / "web-search-recipe.md").write_text(
        "---\nname: web-search-recipe\ndescription: d\ntrust: builtin\nenabled: true\n---\n# w\n", encoding="utf-8",
    )
    (builtin / "git-commit-hygiene.md").write_text(
        "---\nname: git-commit-hygiene\ndescription: d\ntrust: builtin\nenabled: true\n---\n# g\n", encoding="utf-8",
    )
    monkeypatch.setattr(skills, "BUILTIN_DIR", builtin)
    monkeypatch.setattr(skills, "USER_DIR", user)

    table = {
        "py-test-runner": [1.0, 0.0, 0.0],
        "web-search-recipe": [0.0, 1.0, 0.0],
        "git-commit-hygiene": [0.0, 0.0, 1.0],
    }
    def fake_emb(texts):
        if len(texts) == 1:
            return [[1.0, 0.0, 0.0]]
        return [table.get(t.split("\n", 1)[0], [0.0, 0.0, 0.0]) for t in texts]
    _use_embedder(monkeypatch, fake_emb)

    out = skills.recall("写个单测", k=2, sim_min=0.4)
    assert [s.name for s in out] == ["py-test-runner"]


def test_recall_filters_below_simmin(skills_dir, monkeypatch, tmp_path):
    def fake_emb(texts):
        if len(texts) == 1:
            return [[1.0, 0.0]]
        return [[0.0, 1.0] for _ in texts]
    _use_embedder(monkeypatch, fake_emb)
    out = skills.recall("goal", k=3, sim_min=0.4)
    assert out == []


def test_recall_embed_failure_falls_back_to_keyword(skills_dir, monkeypatch, tmp_path):
    def boom(_texts):
        raise RuntimeError("simulated embedding failure")
    _use_embedder(monkeypatch, boom)
    assert "a" in {s.name for s in skills.recall("alpha 的活", k=3)}
    assert skills.recall("zzz unrelated", k=3) == []


def test_recall_excludes_disabled(skills_dir, monkeypatch, tmp_path):
    def fake_emb(texts):
        return [[1.0, 0.0] for _ in texts]
    _use_embedder(monkeypatch, fake_emb)
    out = skills.recall("goal", k=3, sim_min=0.4)
    assert {s.name for s in out} == {"a", "c"}
