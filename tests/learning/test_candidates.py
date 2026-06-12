"""candidates:候选落盘/读取/消费标记。"""
from pathlib import Path

from argos_agent.learning.candidates import (
    StoredCandidate, save_candidate, list_unconsumed, mark_consumed,
)
from argos_agent.learning.distiller import SkillCandidate


def _cand(name: str = "fix-login") -> SkillCandidate:
    return SkillCandidate(
        name=name, body_markdown=f"# {name}\nbody",
        verify_cmd="pytest -q", skill_md_path=Path("unused"),
    )


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
    # 标记是写 meta,不是删目录(审计可见)
    assert (p / "meta.json").exists()


def test_list_skips_corrupt_meta(tmp_path: Path):
    d = tmp_path / "bad-run"
    d.mkdir()
    (d / "SKILL.md").write_text("x", encoding="utf-8")
    (d / "meta.json").write_text("{not json", encoding="utf-8")
    assert list_unconsumed(tmp_path) == []  # 坏目录跳过,不抛


def test_save_is_idempotent_per_run(tmp_path: Path):
    save_candidate(_cand(), root=tmp_path, source_run="abc123def45678",
                   workspace=None, goal="g")
    save_candidate(_cand(), root=tmp_path, source_run="abc123def45678",
                   workspace=None, goal="g")
    assert len(list_unconsumed(tmp_path)) == 1  # 同 run 同名只存一份


def test_save_sanitizes_path_traversal_name(tmp_path: Path):
    """I1 防穿越:name 含 ../ 不得逃出 root,落盘必须留在 tmp_path 内。"""
    p = save_candidate(_cand(name="../evil"), root=tmp_path,
                       source_run="abc123def45678", workspace=None, goal="g")
    assert p is not None
    assert p.resolve().is_relative_to(tmp_path.resolve())  # 没逃出候选区
    assert len(list_unconsumed(tmp_path)) == 1  # 仍可读到这 1 条
    # root 之外(tmp_path 的父目录)绝不能出现 evil 开头的目录
    assert not [d for d in tmp_path.parent.iterdir()
                if d.name.startswith("evil")]


def test_list_drops_self_verified_candidates(tmp_path: Path):
    """E4 纵深防御(评审 B1):候选是持久产物,上游防线之外这里必须再挡一道。

    meta 标 self_verified=True 的候选绝不能进 Dream 材料 —— 万一上游路由
    变化或有人手工放入,材料层兜底。
    """
    import json
    p = save_candidate(_cand(), root=tmp_path, source_run="abc123def45678",
                       workspace=None, goal="g")
    meta_path = p / "meta.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    assert meta["self_verified"] is False  # 默认必须显式落盘 False(来源可审计)
    meta["self_verified"] = True
    meta_path.write_text(json.dumps(meta), encoding="utf-8")
    assert list_unconsumed(tmp_path) == []
