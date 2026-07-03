from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path

import pytest

import argos.skills as skills_mod
from argos.learning import dream
from argos.learning.candidates import save_candidate
from argos.learning.distiller import SkillCandidate


# ── fake runners ─────────────────────────────────────────────────────────────

@dataclass
class _FakeResult:
    pass_status: str


class _PassRunner:
    def run(self, task, *, model_tier: str):
        return _FakeResult(pass_status="passed")


class _FailRunner:
    def run(self, task, *, model_tier: str):
        return _FakeResult(pass_status="failed")



def _seed_candidate(
    cand_root: Path, *,
    run: str,
    goal: str,
    workspace: Path,
    verify_cmd: str = "true",
) -> Path:
    cand = SkillCandidate(
        name="learned",
        body_markdown=f"# {goal}\n\n```python\nprint('ok')\n```",
        verify_cmd=verify_cmd,
        skill_md_path=Path("unused"),
    )
    p = save_candidate(
        cand, root=cand_root, source_run=run,
        workspace=str(workspace), goal=goal,
    )
    assert p is not None, f"save_candidate 失败（run={run}）"
    return p



def test_dream_promote_and_load_end_to_end(tmp_path: Path, monkeypatch):
    cand_root = tmp_path / "candidates"
    skills_root = tmp_path / "skills"
    ws = tmp_path / "ws"
    ws.mkdir()

    _seed_candidate(cand_root, run="e2e0001aaaa11", goal="fix login auth bug",
                    workspace=ws, verify_cmd="true")
    _seed_candidate(cand_root, run="e2e0002bbbb22", goal="fix login auth timeout bug",
                    workspace=ws, verify_cmd="true")

    def runner_factory(hint):
        return _PassRunner() if hint is not None else _FailRunner()

    monkeypatch.setattr(skills_mod, "USER_DIR", skills_root)

    events: list[dict] = []

    def broadcast(payload: dict) -> None:
        events.append(payload)

    pipe = dream.DreamPipeline(
        candidates_root=cand_root,
        skills_root=skills_root,
        memory_dir=tmp_path / "memory",
        dreams_dir=tmp_path / "dreams",
        runner_factory=runner_factory,
        broadcast_fn=broadcast,
    )

    report = asyncio.run(pipe.run())

    skill_mds = list(skills_root.glob("*/SKILL.md"))
    assert len(skill_mds) == 1, (
        f"期望恰好 1 个晋升产物(*/SKILL.md)，实得 {skill_mds}；"
        "若为 0，说明 review#1(loop_factory) 未生效 —— promote 未走晋升分支"
    )

    assert report is not None
    assert report.promoted == 1, (
        f"期望 report.promoted==1，实得 {report.promoted}"
    )

    promoted_skill_name = skill_mds[0].parent.name

    loaded_names = [s.name for s in skills_mod.load_all()]
    skill_md_text = skill_mds[0].read_text(encoding="utf-8")
    import re
    fm_name_match = re.search(r"^name:\s+(.+)$", skill_md_text, re.MULTILINE)
    assert fm_name_match, f"晋升的 SKILL.md 中未找到 name 字段:\n{skill_md_text[:400]}"
    frontmatter_name = fm_name_match.group(1).strip()

    assert frontmatter_name in loaded_names, (
        f"skills.load_all() 未返回晋升技能 {frontmatter_name!r}；"
        f"已加载的技能名: {loaded_names}；"
        "若列表不含该名，说明 review#2(skills loader 子目录扫描) 未生效"
    )
