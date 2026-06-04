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


# ── recall(): cosine top-k + sim_min + 嵌入失败降级 ─────────────────────────

class _FakeEmbedder:
    """注入用 embedder 替身:embed(texts)->vectors。recall 现走 config.active_embedder()。"""
    dim = 8

    def __init__(self, fn):
        self._fn = fn

    def embed(self, texts):
        return self._fn(texts)


def _use_embedder(monkeypatch, fn):
    """让 skills.recall 用注入的 embedder(替代旧的直连 MiniMax llm_embed)。"""
    monkeypatch.setattr("argos_agent.config.active_embedder", lambda: _FakeEmbedder(fn))


def test_recall_returns_empty_when_no_embedder(skills_dir, monkeypatch):
    """未配 embedding(active_embedder 返 None)→ 记忆/skill 召回降级返空,不绑定不偷调。"""
    monkeypatch.setattr("argos_agent.config.active_embedder", lambda: None)
    assert skills.recall("anything", k=3, sim_min=0.4) == []


def test_recall_returns_top_k_enabled_by_cosine(monkeypatch, tmp_path):
    # 自含 3 个 skill,embed_text 按 name 返确定向量
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
        # goal(1 elem)→ [1,0,0](与 py-test-runner 强一致);skill(多 elem)按 name
        if len(texts) == 1:
            return [[1.0, 0.0, 0.0]]
        return [table.get(t.split("\n", 1)[0], [0.0, 0.0, 0.0]) for t in texts]
    _use_embedder(monkeypatch, fake_emb)

    out = skills.recall("写个单测", k=2, sim_min=0.4)
    assert [s.name for s in out] == ["py-test-runner"]


def test_recall_filters_below_simmin(skills_dir, monkeypatch, tmp_path):
    # 一个 skill enabled=true 但向量与 goal 正交 → 应被 sim_min 滤掉
    def fake_emb(texts):
        # goal 走 [1,0],各 skill 走 [0,1](正交,sim=0)
        if len(texts) == 1:
            return [[1.0, 0.0]]
        return [[0.0, 1.0] for _ in texts]
    _use_embedder(monkeypatch, fake_emb)
    out = skills.recall("goal", k=3, sim_min=0.4)
    assert out == []


def test_recall_returns_empty_when_embed_fails(skills_dir, monkeypatch, tmp_path):
    def boom(_texts):
        raise RuntimeError("simulated embedding failure")
    _use_embedder(monkeypatch, boom)
    out = skills.recall("anything", k=3, sim_min=0.4)
    assert out == []


def test_recall_excludes_disabled(skills_dir, monkeypatch, tmp_path):
    def fake_emb(texts):
        return [[1.0, 0.0] for _ in texts]  # 全相同 → 全 sim=1
    _use_embedder(monkeypatch, fake_emb)
    out = skills.recall("goal", k=3, sim_min=0.4)
    # b.md 是 enabled=false;a,c 是 enabled=true → 应只返 a, c
    assert {s.name for s in out} == {"a", "c"}
