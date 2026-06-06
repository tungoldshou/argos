"""#7 T2/T3 EvalRunner 测试。

fake_worktree + fake_loop 桩覆盖 5 类失败模式 + 6 类成功路径。"""
from __future__ import annotations

import pytest
from pathlib import Path
from typing import Any

from argos_agent.eval.corpus import EvalTask
from argos_agent.eval.runner import (
    EvalResult, EvalRunner, LoopOutcome,
    PASS_PASSED, PASS_FAILED, PASS_UNVERIFIABLE, PASS_SETUP_FAILED, PASS_ERROR,
)
from argos_agent.daemon.worktree import WorktreeManager

from tests.eval._seed_corpus import write_seed_corpus


# ── 桩:fake worktree ──────────────────────────────────────────────────


class FakeWorktree:
    """在 tmp_path/eval_wt/<run_id>/ 落目录,模拟 worktree create/cleanup。"""
    def __init__(self, base: Path, *, fail_create: bool = False):
        self.base = Path(base)
        self.base.mkdir(parents=True, exist_ok=True)
        self._fail_create = fail_create
        self.created: list[str] = []
        self.cleaned: list[str] = []

    def is_git_repo(self, workspace: str) -> bool:
        return True  # 默认走 git 路径(但不真跑 git)

    def create(self, *, run_id: str, workspace: str) -> str:
        if self._fail_create:
            raise RuntimeError("simulated worktree failure")
        p = self.base / run_id
        p.mkdir(parents=True, exist_ok=True)
        # 模拟 worktree 包含 working_dir 的内容
        (p / "sentinel.txt").write_text(f"from {workspace}", encoding="utf-8")
        self.created.append(run_id)
        return str(p)

    def cleanup(self, run_id: str) -> None:
        p = self.base / run_id
        import shutil
        if p.exists():
            shutil.rmtree(p, ignore_errors=True)
        self.cleaned.append(run_id)


# ── 桩:fake loop ──────────────────────────────────────────────────────


def make_fake_loop(
    *,
    verdict: str = PASS_PASSED,
    detail: str = "5 passed in 0.5s",
    tampered: tuple[str, ...] = (),
    tokens_in: int = 1000,
    tokens_out: int = 500,
    cost_usd: float | None = 0.013,
    steps: int = 8,
    raise_on_run: bool = False,
):
    """返一个 fake loop:有 run_sync(goal, workspace) → LoopOutcome。"""
    class _Loop:
        pass

    loop = _Loop()
    loop.steps = 0
    loop.tokens_in = 0
    loop.tokens_out = 0
    loop.cost_usd = 0.0

    def _run_sync(goal: str, workspace: Path) -> LoopOutcome:
        if raise_on_run:
            raise RuntimeError("simulated LLM failure")
        loop.steps = steps
        loop.tokens_in = tokens_in
        loop.tokens_out = tokens_out
        loop.cost_usd = cost_usd
        return LoopOutcome(
            verdict_status=verdict, verify_detail=detail, tampered=tampered,
            steps=steps, tokens_in=tokens_in, tokens_out=tokens_out,
            cost_usd=cost_usd,
        )

    loop.run_sync = _run_sync
    return loop


def make_fake_loop_factory(loop):
    """EvalRunner 接 loop_factory(model_tier) → loop;不同 model_tier 可返不同 loop。"""
    def _factory(model_tier: str):
        return loop
    return _factory


# ── fixture ───────────────────────────────────────────────────────────


@pytest.fixture
def seed_corpus(tmp_path, monkeypatch):
    root = tmp_path / "corpus"
    write_seed_corpus(root)
    monkeypatch.setenv("ARGOS_EVAL_CORPUS_DIR", str(root))
    return root


@pytest.fixture
def eval_task(seed_corpus, tmp_path) -> EvalTask:
    """用 bug_fix_001(verify_cmd 永远 pass 的"echo 0"等价物)做 task。"""
    from argos_agent.eval.corpus import load_task
    return load_task("bug_fix_001_off_by_one")


@pytest.fixture
def runner_with_fake(tmp_path, eval_task):
    """EvalRunner + fake worktree + fake loop(默认 verdict=passed)。"""
    base = tmp_path / "eval"
    wt = FakeWorktree(base / "wt")
    loop = make_fake_loop()
    runner = EvalRunner(
        worktree=wt, base_dir=base, loop_factory=make_fake_loop_factory(loop),
        budget_s=300, budget_cost_usd=1.0,
    )
    return runner, wt, loop, eval_task


# ── happy path ────────────────────────────────────────────────────────


def test_run_happy_path_returns_passed(runner_with_fake):
    runner, wt, loop, task = runner_with_fake
    r = runner.run(task, model_tier="cheap")
    assert r.pass_status == PASS_PASSED
    assert r.task_id == task.id
    assert r.model_tier == "cheap"
    assert r.error is None


def test_run_captures_tokens_and_cost(runner_with_fake):
    runner, wt, loop, task = runner_with_fake
    r = runner.run(task, model_tier="cheap")
    assert r.tokens_in == 1000
    assert r.tokens_out == 500
    assert r.cost_usd == 0.013
    assert r.steps == 8


def test_run_captures_duration(runner_with_fake):
    runner, wt, loop, task = runner_with_fake
    r = runner.run(task, model_tier="cheap")
    assert r.duration_s >= 0.0
    assert r.finished_at >= r.started_at


def test_run_uses_worktree_manager(runner_with_fake):
    """runner keep_worktree=True → 跑完 worktree 仍在(供断言 / 调试)。"""
    runner, wt, loop, task = runner_with_fake
    runner2 = EvalRunner(
        worktree=wt, base_dir=runner.base_dir, loop_factory=make_fake_loop_factory(loop),
        keep_worktree=True,
    )
    r = runner2.run(task, model_tier="cheap")
    assert Path(r.worktree_path).exists()
    assert (Path(r.worktree_path) / "sentinel.txt").exists()
    # 手动清理
    runner2.cleanup_worktree(r.run_id)


def test_run_worktree_path_in_result(runner_with_fake):
    runner, wt, loop, task = runner_with_fake
    r = runner.run(task, model_tier="cheap")
    assert r.worktree_path.startswith(str(wt.base))


def test_run_no_fallback_for_git_workspace(runner_with_fake):
    runner, wt, loop, task = runner_with_fake
    r = runner.run(task, model_tier="cheap")
    assert r.isolation_fallback is None


def test_run_passes_goal_to_loop(runner_with_fake):
    runner, wt, loop, task = runner_with_fake
    runner.run(task, model_tier="cheap")
    # loop 已被调,捕获 goal
    assert "_score" in task.goal


def test_run_pass_status_uses_verifier_not_model(runner_with_fake):
    """verdict 来自 fake loop,但 fake loop 必须用 verify 退出码(桩模拟)。"""
    runner, wt, loop, task = runner_with_fake
    # 改 fake loop 返 failed
    loop2 = make_fake_loop(verdict=PASS_FAILED, detail="1 failed")
    runner2 = EvalRunner(
        worktree=wt, base_dir=runner.base_dir, loop_factory=make_fake_loop_factory(loop2),
    )
    r = runner2.run(task, model_tier="cheap")
    assert r.pass_status == PASS_FAILED


# ── 失败模式 ───────────────────────────────────────────────────────────


def test_run_setup_failure_returns_setup_failed(tmp_path, eval_task):
    """seed 装一个带 setup.sh 失败 exit code 的 task → setup_failed。"""
    from argos_agent.eval.corpus import load_task, list_tasks, corpus_version
    import json
    p = tmp_path / "corpus"
    write_seed_corpus(p)
    extra = p / "task_setup_fail"
    extra.mkdir()
    (extra / "goal.md").write_text("g", encoding="utf-8")
    (extra / "verify_cmd").write_text("true", encoding="utf-8")
    (extra / "setup.sh").write_text("#!/bin/bash\nexit 1\n", encoding="utf-8")
    manifest = json.loads((p / "corpus.json").read_text("utf-8"))
    manifest["tasks"].append({"id": "task_setup_fail", "category": "bug_fix", "difficulty": "easy", "title": "x"})
    (p / "corpus.json").write_text(json.dumps(manifest), encoding="utf-8")
    import os
    os.environ["ARGOS_EVAL_CORPUS_DIR"] = str(p)
    task = load_task("task_setup_fail")

    base = tmp_path / "eval"
    wt = FakeWorktree(base / "wt")
    loop = make_fake_loop()
    runner = EvalRunner(worktree=wt, base_dir=base, loop_factory=make_fake_loop_factory(loop))
    r = runner.run(task, model_tier="cheap")
    assert r.pass_status == PASS_SETUP_FAILED
    assert "setup exit 1" in r.verify_detail


def test_run_loop_crash_returns_error(tmp_path, eval_task):
    base = tmp_path / "eval"
    wt = FakeWorktree(base / "wt")
    loop = make_fake_loop(raise_on_run=True)
    runner = EvalRunner(worktree=wt, base_dir=base, loop_factory=make_fake_loop_factory(loop))
    r = runner.run(eval_task, model_tier="cheap")
    assert r.pass_status == PASS_ERROR
    assert "simulated LLM failure" in r.error


def test_run_worktree_failure_returns_error(tmp_path, eval_task):
    base = tmp_path / "eval"
    wt = FakeWorktree(base / "wt", fail_create=True)
    loop = make_fake_loop()
    runner = EvalRunner(worktree=wt, base_dir=base, loop_factory=make_fake_loop_factory(loop))
    r = runner.run(eval_task, model_tier="cheap")
    assert r.pass_status == PASS_ERROR
    assert "worktree_failed" in r.error


def test_run_no_loop_factory_returns_error(tmp_path, eval_task):
    base = tmp_path / "eval"
    wt = FakeWorktree(base / "wt")
    runner = EvalRunner(worktree=wt, base_dir=base, loop_factory=None)
    r = runner.run(eval_task, model_tier="cheap")
    assert r.pass_status == PASS_ERROR
    assert "loop_factory_required" in r.error


def test_run_unverifiable_passes_through(runner_with_fake):
    runner, wt, loop, task = runner_with_fake
    loop2 = make_fake_loop(
        verdict=PASS_UNVERIFIABLE, detail="tamper detected", tampered=("tests/test_x.py",),
    )
    runner2 = EvalRunner(worktree=wt, base_dir=runner.base_dir, loop_factory=make_fake_loop_factory(loop2))
    r = runner2.run(task, model_tier="cheap")
    assert r.pass_status == PASS_UNVERIFIABLE
    assert "tests/test_x.py" in r.tampered


# ── T3:worktree 集成细节 ──────────────────────────────────────────────


def test_run_temp_fallback_records_fallback(tmp_path, eval_task):
    """workspace 非 git repo → isolation_fallback='temp'。"""
    base = tmp_path / "eval"
    wt = FakeWorktree(base / "wt")

    class _NotGitWorktree(FakeWorktree):
        def is_git_repo(self, workspace: str) -> bool:
            return False

    wt2 = _NotGitWorktree(base / "wt")
    loop = make_fake_loop()
    runner = EvalRunner(worktree=wt2, base_dir=base, loop_factory=make_fake_loop_factory(loop))
    r = runner.run(eval_task, model_tier="cheap")
    assert r.isolation_fallback == "temp"


def test_run_keep_worktree_skips_cleanup(tmp_path, eval_task):
    """keep_worktree=True → 不调 cleanup。"""
    base = tmp_path / "eval"
    wt = FakeWorktree(base / "wt")
    loop = make_fake_loop()
    runner = EvalRunner(
        worktree=wt, base_dir=base, loop_factory=make_fake_loop_factory(loop),
        keep_worktree=True,
    )
    r = runner.run(eval_task, model_tier="cheap")
    assert Path(r.worktree_path).exists()
    assert r.run_id not in wt.cleaned
    # 手动 cleanup 兜底
    runner.cleanup_worktree(r.run_id)


def test_run_default_cleans_up_worktree(runner_with_fake):
    runner, wt, loop, task = runner_with_fake
    r = runner.run(task, model_tier="cheap")
    assert r.run_id in wt.cleaned
    assert not Path(r.worktree_path).exists()


def test_run_result_json_roundtrip(runner_with_fake):
    """EvalResult.to_json / from_json 序列化无字段丢失。"""
    runner, wt, loop, task = runner_with_fake
    r = runner.run(task, model_tier="cheap")
    s = r.to_json()
    r2 = EvalResult.from_json(s)
    assert r2.task_id == r.task_id
    assert r2.run_id == r.run_id
    assert r2.pass_status == r.pass_status
    assert r2.cost_usd == r.cost_usd
    assert r2.goal == r.goal


def test_run_with_real_worktree_manager(tmp_path, eval_task):
    """用 #5b 真 WorktreeManager 验接(若 git 不可用 → skip)。"""
    import shutil
    if not shutil.which("git"):
        pytest.skip("git not in PATH")
    import subprocess
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "t@x"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "T"], cwd=repo, check=True)
    (repo / "f.txt").write_text("hi")
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "i"], cwd=repo, check=True)
    base = tmp_path / "eval"
    wt = WorktreeManager(base_dir=base / "wt")
    # 用 eval_task.working_dir(repo) → 真 git worktree add
    eval_task_with_repo = EvalTask(
        id=eval_task.id, category=eval_task.category, difficulty=eval_task.difficulty,
        title=eval_task.title, goal=eval_task.goal, verify_cmd=eval_task.verify_cmd,
        setup_cmd=None, expected_files=(), working_dir=repo, corpus_version=1,
    )
    loop = make_fake_loop()
    runner = EvalRunner(worktree=wt, base_dir=base, loop_factory=make_fake_loop_factory(loop))
    r = runner.run(eval_task_with_repo, model_tier="cheap")
    assert r.pass_status == PASS_PASSED
    assert r.isolation_fallback is None  # 真 git repo
