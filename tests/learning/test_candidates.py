"""Internal documentation."""
from pathlib import Path

from argos.learning.candidates import (
    StoredCandidate, save_candidate, list_unconsumed, mark_consumed,
)
from argos.learning.distiller import SkillCandidate


def _cand(name: str = "fix-login") -> SkillCandidate:
    return SkillCandidate(
        name=name, body_markdown=f"# {name}\nbody",
        verify_cmd="pytest -q", skill_md_path=Path("unused"),
    )


def test_default_root_honors_argos_config_dir(tmp_path: Path, monkeypatch):
    from argos.learning import candidates

    cfg_dir = tmp_path / ".argos"
    monkeypatch.setenv("ARGOS_CONFIG_DIR", str(cfg_dir))
    monkeypatch.setattr(candidates, "DEFAULT_ROOT", None)

    assert candidates.default_root() == cfg_dir / "learning" / "candidates"


def test_save_then_list_roundtrip(tmp_path: Path):
    p = save_candidate(
        _cand(), root=tmp_path, source_run="abc123def45678",
        workspace="/tmp/proj", goal="fix login",
    )
    assert p is not None
    assert (p / "SKILL.md").exists() and (p / "meta.json").exists()
    got = list_unconsumed(tmp_path)
    assert len(got) == 1
    sc = got[0]
    assert sc.name == "fix-login"
    assert sc.source_run == "abc123def45678"
    assert sc.verify_cmd == "pytest -q"
    assert sc.workspace == "/tmp/proj"
    assert sc.goal == "fix login"
    assert "body" in sc.body_markdown


def test_mark_consumed_excludes_from_list(tmp_path: Path):
    p = save_candidate(_cand(), root=tmp_path, source_run="abc123def45678",
                       workspace=None, goal="g")
    mark_consumed(p, reason="promoted")
    assert list_unconsumed(tmp_path) == []
    assert (p / "meta.json").exists()


def test_list_skips_corrupt_meta(tmp_path: Path):
    d = tmp_path / "bad-run"
    d.mkdir()
    (d / "SKILL.md").write_text("x", encoding="utf-8")
    (d / "meta.json").write_text("{not json", encoding="utf-8")
    assert list_unconsumed(tmp_path) == []


def test_save_is_idempotent_per_run(tmp_path: Path):
    save_candidate(_cand(), root=tmp_path, source_run="abc123def45678",
                   workspace=None, goal="g")
    save_candidate(_cand(), root=tmp_path, source_run="abc123def45678",
                   workspace=None, goal="g")
    assert len(list_unconsumed(tmp_path)) == 1


def test_save_sanitizes_path_traversal_name(tmp_path: Path):
    """Internal documentation."""
    p = save_candidate(_cand(name="../evil"), root=tmp_path,
                       source_run="abc123def45678", workspace=None, goal="g")
    assert p is not None
    assert p.resolve().is_relative_to(tmp_path.resolve())
    assert len(list_unconsumed(tmp_path)) == 1
    assert not [d for d in tmp_path.parent.iterdir()
                if d.name.startswith("evil")]


def test_save_candidate_redacts_meta(tmp_path: Path):
    """Internal documentation."""
    import json
    from argos.learning.candidates import save_candidate
    from argos.learning.distiller import SkillCandidate

    secret_goal = "fetch data with key sk-ant-xxxxxxxxxxxxxxxxxxxx and password=\"hunter2\""
    secret_verify = "AKIA1234567890123456 pytest -q"
    cand = SkillCandidate(
        name="secret-skill",
        body_markdown="# secret-skill\nbody",
        verify_cmd=secret_verify,
        skill_md_path=Path("unused"),
    )
    p = save_candidate(
        cand, root=tmp_path, source_run="abc123def45678",
        workspace="/tmp/ws", goal=secret_goal,
    )
    assert p is not None
    meta = json.loads((p / "meta.json").read_text(encoding="utf-8"))
    meta_str = json.dumps(meta)
    assert "sk-ant-xxxxxxxxxxxxxxxxxxxx" not in meta_str,\
        "sk-ant- 明文出现在 meta.json — 脱敏失效"
    assert "hunter2" not in meta_str,\
        "password=hunter2 明文出现在 meta.json — 脱敏失效"
    assert "AKIA1234567890123456" not in meta_str,\
        "AKIA 明文出现在 meta.json — 脱敏失效"
    assert "<redacted:secret>" in meta_str, "脱敏后应有 <redacted:secret> 占位符"


def test_list_drops_self_verified_candidates(tmp_path: Path):
    """Internal documentation."""
    import json
    p = save_candidate(_cand(), root=tmp_path, source_run="abc123def45678",
                       workspace=None, goal="g")
    meta_path = p / "meta.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    assert meta["self_verified"] is False
    meta["self_verified"] = True
    meta_path.write_text(json.dumps(meta), encoding="utf-8")
    assert list_unconsumed(tmp_path) == []
