"""learning promotion_gate 验收 — 任务:A/B 不提升的候选不被晋升;提升才晋升。

约束:
- 复用 eval/runner.py + eval/compare.py 的 run_pair(同 model_tier 跑两次,B 路径在
  loop_factory 里注入技能 hint)
- builtin 名字硬拒(reuse skills_curator.BUILTIN_NAMES)
- 不调真 worktree(测试桩)
- 落盘:promoted=True 才写 ~/.argos/skills/<name>/SKILL.md
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest

from argos_agent.learning import promotion_gate


@dataclass
class _FakeOutcome:
    verdict_status: str = "passed"
    verify_detail: str = "ok"
    tampered: tuple = ()
    steps: int = 1
    tokens_in: int = 10
    tokens_out: int = 5
    cost_usd: float | None = 0.001


@dataclass
class _FakeLoop:
    """带 hint 注入的 fake loop:跑出结果由 caller 控制 pass_status 序列。"""
    hint: str | None = None
    pass_sequence: list[str] = field(default_factory=lambda: ["passed"])

    def run_sync(self, goal: str, workspace: Path) -> _FakeOutcome:
        # 取下一个预定 verdict(测试通过外部传 sequence 控制 A/B 通过率)
        status = self.pass_sequence.pop(0) if self.pass_sequence else "passed"
        return _FakeOutcome(verdict_status=status)


class _FakeRunner:
    """假 runner:每 task 跑两次,两次分别用 pass_sequence_a / pass_sequence_b 喂 loop。"""
    def __init__(self, sequence_a: list[str], sequence_b: list[str]):
        self._seq_a = list(sequence_a)
        self._seq_b = list(sequence_b)
        self._counter = 0
        self.base_dir = Path("/tmp/fake_eval")

    def run(self, task, *, model_tier: str) -> Any:
        # 偶数次用 seq_a(A=无 hint),奇数次用 seq_b(B=有 hint)
        self._counter += 1
        if self._counter % 2 == 1:
            return self._run_once(task, self._seq_a, hint=None, model_tier=model_tier)
        return self._run_once(task, self._seq_b, hint="<candidate skill body>", model_tier=model_tier)

    def _run_once(self, task, seq, *, hint, model_tier: str):
        # 跑一个 EvalResult-look-alike。直接用 eval.runner.EvalResult 避免重复定义。
        from argos_agent.eval.runner import EvalResult, PASS_PASSED, PASS_FAILED
        outcome = _FakeLoop(hint=hint, pass_sequence=seq).run_sync(task.goal, task.working_dir)
        status = outcome.verdict_status
        return EvalResult(
            task_id=task.id, run_id=f"r{self._counter}", model_tier=model_tier,
            started_at=0.0, finished_at=0.0, duration_s=0.0,
            pass_status=status, verify_cmd=task.verify_cmd,
            verify_detail=outcome.verify_detail, tampered=(),
            tokens_in=outcome.tokens_in, tokens_out=outcome.tokens_out,
            cost_usd=outcome.cost_usd, steps=outcome.steps,
            worktree_path="", isolation_fallback=None, error=None,
            corpus_version=task.corpus_version, goal=task.goal,
        )


def _make_task(task_id: str = "t#1", verify_cmd: str = "true"):
    from argos_agent.eval.corpus import EvalTask
    return EvalTask(
        id=task_id, category="self_check", difficulty="easy",
        title=f"task {task_id}", goal=f"goal {task_id}", verify_cmd=verify_cmd,
        setup_cmd=None, expected_files=(), working_dir=Path("/tmp"),
        corpus_version=1,
    )


def _make_candidate(name: str, body: str = "# skill body", verify_cmd: str = "true"):
    from argos_agent.learning.distiller import SkillCandidate
    return SkillCandidate(
        name=name, body_markdown=body, verify_cmd=verify_cmd,
        skill_md_path=Path(f"/tmp/skills/{name}/SKILL.md"),
    )


# ── 验收 b: A/B 不提升的候选不被晋升 ─────────────────────
def test_promoted_when_pass_rate_improves(tmp_path):
    """A=0/2 passed, B=2/2 passed → promoted=True,B 严格 > A。"""
    from argos_agent.learning.distiller import SkillCandidate

    tasks = [_make_task("t1"), _make_task("t2")]
    runner = _FakeRunner(sequence_a=["failed", "failed"], sequence_b=["passed", "passed"])
    cand = _make_candidate("learned-good")

    result = promotion_gate.promote(
        candidate=cand, tasks=tasks, runner=runner,
        skills_root=tmp_path / "skills",
    )
    assert result.promoted is True, f"应晋升,实得 {result}"
    # 落盘
    assert (tmp_path / "skills" / "learned-good" / "SKILL.md").exists()


def test_not_promoted_when_no_improvement(tmp_path):
    """A=1/2, B=1/2 → promoted=False(B 没 > A,平手不晋升)。"""
    tasks = [_make_task("t1"), _make_task("t2")]
    runner = _FakeRunner(sequence_a=["passed", "failed"], sequence_b=["passed", "failed"])
    cand = _make_candidate("learned-tie")

    result = promotion_gate.promote(
        candidate=cand, tasks=tasks, runner=runner,
        skills_root=tmp_path / "skills",
    )
    assert result.promoted is False
    # 落盘拒绝
    assert not (tmp_path / "skills" / "learned-tie" / "SKILL.md").exists()


def test_not_promoted_when_regression(tmp_path):
    """A=2/2, B=1/2 → promoted=False(B 反而差,防退化)。"""
    tasks = [_make_task("t1"), _make_task("t2")]
    runner = _FakeRunner(sequence_a=["passed", "passed"], sequence_b=["passed", "failed"])
    cand = _make_candidate("learned-bad")

    result = promotion_gate.promote(
        candidate=cand, tasks=tasks, runner=runner,
        skills_root=tmp_path / "skills",
    )
    assert result.promoted is False
    assert not (tmp_path / "skills" / "learned-bad" / "SKILL.md").exists()


def test_builtin_name_rejected(tmp_path):
    """候选 name 命中 BUILTIN_NAMES → 即返 rejected(不跑 A/B,免测)。"""
    from argos_agent.skills_curator.index import BUILTIN_NAMES
    builtin = next(iter(BUILTIN_NAMES))
    cand = _make_candidate(builtin)
    # runner 永远不应用
    runner = _FakeRunner(sequence_a=[], sequence_b=[])
    result = promotion_gate.promote(
        candidate=cand, tasks=[_make_task()], runner=runner,
        skills_root=tmp_path / "skills",
    )
    assert result.promoted is False
    assert "builtin" in (result.reason or "").lower()


def test_promote_swallows_runner_exceptions(tmp_path):
    """A/B runner 抛异常 → promoted=False,reason 标"runner_error",不抛给 caller。"""
    class _BoomRunner(_FakeRunner):
        def run(self, task, *, model_tier):
            raise RuntimeError("boom")

    cand = _make_candidate("learned-boom")
    result = promotion_gate.promote(
        candidate=cand, tasks=[_make_task()], runner=_BoomRunner([], []),
        skills_root=tmp_path / "skills",
    )
    assert result.promoted is False
    assert not (tmp_path / "skills" / "learned-boom").exists()


def test_promote_writes_frontmatter_enabled_false(tmp_path):
    """晋升落盘后,SKILL.md 应含 enabled: false(沿用 install 的 user review gate)。

    body 由 distill 阶段生成(带 frontmatter),promotion_gate 透传不重写。
    """
    tasks = [_make_task("t1"), _make_task("t2")]
    runner = _FakeRunner(sequence_a=["failed", "failed"], sequence_b=["passed", "passed"])
    body_with_fm = (
        "---\nname: learned-review\nenabled: false\n---\n\n"
        "# learned skill body\ndo the thing\n"
    )
    cand = _make_candidate("learned-review", body=body_with_fm)

    promotion_gate.promote(
        candidate=cand, tasks=tasks, runner=runner,
        skills_root=tmp_path / "skills",
    )
    skill_md = (tmp_path / "skills" / "learned-review" / "SKILL.md").read_text()
    assert "enabled: false" in skill_md
    assert "learned skill body" in skill_md
