"""联合端到端回归测试：Dream 晋升 → 加载闭环（review #1 + #2 协同证明）。

本测试钉死两个已提交修复叠加后的核心闭环：
  #1 (3b9a896)：cli 补 loop_factory —— A/B runner_factory 接线正确，promote 能正常跑出晋升
  #2 (a4910b9)：skills.load_all/toggle 补扫 <name>/SKILL.md 子目录 —— 晋升落盘后 load_all 能读到

联合证明规则（任一修复未到位，测试必 FAIL）：
  (a) skills_root/<name>/SKILL.md 真被写（#1 修复后 A/B 能跑出 b_passed > a_passed → promote 落盘）
      若 #1 未修：loop_factory 缺失 → promote 内 runner_factory(None) 接口错误
      → A/B 恒 PASS_ERROR / runner_error → 永不晋升 → (a) FAIL
  (b) skills.load_all() 返回的技能名包含晋升技能（#2 修复后 load_all 扫 */SKILL.md 子目录）
      若 #2 未修：load_all 只扫 *.md 平铺文件 → 扫不到子目录产物 → (b) FAIL

fake pass-runner 策略：
  - B 侧：runner_factory(hint) 中 hint 非 None → _PassRunner（passed）
  - A 侧：runner_factory(hint) 中 hint = None  → _FailRunner（failed）
  - 结果：b_passed=N > a_passed=0 → 严格提升 → 晋升

注意：promotion_gate 不感知 hint，靠 DreamPipeline._process_unit 的
  runner_factory(None) = A 侧 / runner_factory(cand.body_markdown) = B 侧 分流。
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path

import pytest

import argos_agent.skills as skills_mod
from argos_agent.learning import dream
from argos_agent.learning.candidates import save_candidate
from argos_agent.learning.distiller import SkillCandidate


# ── fake runners ─────────────────────────────────────────────────────────────

@dataclass
class _FakeResult:
    """EvalResult-look-alike：promote 只读 pass_status。"""
    pass_status: str


class _PassRunner:
    """每个 task 都 passed（B 侧用）。"""
    def run(self, task, *, model_tier: str):
        return _FakeResult(pass_status="passed")


class _FailRunner:
    """每个 task 都 failed（A 侧用 → b_passed > a_passed → 严格提升）。"""
    def run(self, task, *, model_tier: str):
        return _FakeResult(pass_status="failed")


# ── helper：种候选 ────────────────────────────────────────────────────────────

def _seed_candidate(
    cand_root: Path, *,
    run: str,
    goal: str,
    workspace: Path,
    verify_cmd: str = "true",
) -> Path:
    """落一个 SkillCandidate 到候选区，返回候选目录。"""
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


# ── 主测试 ────────────────────────────────────────────────────────────────────

def test_dream_promote_and_load_end_to_end(tmp_path: Path, monkeypatch):
    """晋升 → 落盘 → skills.load_all() 加载 — 联合证明 review#1 + #2 协同。

    (a) skills_root/<name>/SKILL.md 必须被写（#1 链路正常 → promote 落盘）
    (b) skills.load_all() 返回列表中包含晋升技能名（#2 扫子目录修复生效）
    """
    # ── 目录布局 ──────────────────────────────────────────────────────────────
    cand_root = tmp_path / "candidates"
    skills_root = tmp_path / "skills"
    ws = tmp_path / "ws"
    ws.mkdir()   # workspace 必须真实存在（build_eval_tasks 会 .exists() 检查）

    # ── 种 2 个相似候选（goal 共享 "login auth" 主题 → cluster 合为同一 unit） ──
    _seed_candidate(cand_root, run="e2e0001aaaa11", goal="fix login auth bug",
                    workspace=ws, verify_cmd="true")
    _seed_candidate(cand_root, run="e2e0002bbbb22", goal="fix login auth timeout bug",
                    workspace=ws, verify_cmd="true")

    # ── fake runner_factory：hint 非 None → B 侧 pass；hint = None → A 侧 fail ──
    # 这正是 DreamPipeline._process_unit 的调用约定：
    #   runner_factory(None)              → A 侧（无 hint）
    #   runner_factory(cand.body_markdown) → B 侧（hint 非 None）
    def runner_factory(hint):
        return _PassRunner() if hint is not None else _FailRunner()

    # ── monkeypatch skills_mod.USER_DIR 指向 skills_root ──
    # 使 skills.load_all() 扫描的目录就是晋升落盘的目录，不读 ~/.argos/skills
    monkeypatch.setattr(skills_mod, "USER_DIR", skills_root)

    # ── 装配 DreamPipeline（与 test_dream_pipeline.py 手法相同） ──────────────
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

    # ── 跑一轮 Dream ──────────────────────────────────────────────────────────
    report = asyncio.run(pipe.run())

    # ── (a) 落盘断言：skills_root 下有 <name>/SKILL.md 文件 ───────────────────
    # 若 review#1 未修（loop_factory 缺失），promote 内 runner 接线错误
    # → A/B 恒 PASS_ERROR → 永不晋升 → 这里断言 FAIL
    skill_mds = list(skills_root.glob("*/SKILL.md"))
    assert len(skill_mds) == 1, (
        f"期望恰好 1 个晋升产物(*/SKILL.md)，实得 {skill_mds}；"
        "若为 0，说明 review#1(loop_factory) 未生效 —— promote 未走晋升分支"
    )

    # ── 确认 promote 计数正确 ──────────────────────────────────────────────────
    assert report is not None
    assert report.promoted == 1, (
        f"期望 report.promoted==1，实得 {report.promoted}"
    )

    # ── 从落盘文件提取晋升技能的 name 字段 ────────────────────────────────────
    promoted_skill_name = skill_mds[0].parent.name   # 目录名即 slug

    # ── (b) 加载断言：skills.load_all() 扫到晋升产物 ─────────────────────────
    # 若 review#2 未修（load_all 只扫 *.md 平铺），子目录 <name>/SKILL.md 扫不到
    # → 返回列表里没有该技能名 → 这里断言 FAIL
    loaded_names = [s.name for s in skills_mod.load_all()]
    # SKILL.md frontmatter 里的 name 字段（dream-<slug>）是 synthesize() 写入的
    # 晋升文件 name 字段来自 YAML frontmatter；目录名是 slug，frontmatter name 同
    skill_md_text = skill_mds[0].read_text(encoding="utf-8")
    # 从 frontmatter 提取 name:
    import re
    fm_name_match = re.search(r"^name:\s+(.+)$", skill_md_text, re.MULTILINE)
    assert fm_name_match, f"晋升的 SKILL.md 中未找到 name 字段:\n{skill_md_text[:400]}"
    frontmatter_name = fm_name_match.group(1).strip()

    assert frontmatter_name in loaded_names, (
        f"skills.load_all() 未返回晋升技能 {frontmatter_name!r}；"
        f"已加载的技能名: {loaded_names}；"
        "若列表不含该名，说明 review#2(skills loader 子目录扫描) 未生效"
    )
