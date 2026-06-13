"""#7 T9 端到端铁证:e2e_pair_run_compare + 真 fake 桩 + 报告生成。

走 EvalRunner + run_pair + write_report,断言:
  · 2 个 EvalResult 都落 JSONL
  · markdown 报告含 pass winner / cost winner / 字段表
  · json 报告含 winner_pass / winner_cost
  · list_runs 跨 day 能找到
  · summary() 算 pass rate
"""
from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from argos.eval.compare import (
    generate_report, run_pair, write_report, write_report_json,
)
from argos.eval.corpus import EvalTask
from argos.eval.results import list_runs, load_run, summary
from argos.eval.runner import (
    EvalResult, EvalRunner, PASS_PASSED, PASS_FAILED,
)

from tests.eval._fakes import FakeWorktree, make_fake_loop, make_fake_loop_factory
from tests.eval._seed_corpus import write_seed_corpus


def _make_task(root: Path, task_id: str = "bug_fix_001_off_by_one") -> EvalTask:
    from argos.eval.corpus import load_task
    return load_task(task_id)


def test_e2e_pair_run_compare_against_fake_model(tmp_path, monkeypatch):
    """完整链路:corpus → runner → run_pair → 报告 → 读回断言。"""
    root = tmp_path / "corpus"
    write_seed_corpus(root)
    monkeypatch.setenv("ARGOS_EVAL_CORPUS_DIR", str(root))
    monkeypatch.setattr(Path, "home", lambda: tmp_path)

    base = tmp_path / "eval"
    wt = FakeWorktree(base / "wt")
    loop_cheap = make_fake_loop(verdict=PASS_PASSED, cost_usd=0.013, tokens_in=1000, tokens_out=500)
    loop_strong = make_fake_loop(verdict=PASS_PASSED, cost_usd=0.087, tokens_in=5000, tokens_out=2000)
    def factory(model_tier: str):
        return loop_cheap if model_tier == "cheap" else loop_strong
    runner = EvalRunner(worktree=wt, base_dir=base, loop_factory=factory)
    task = _make_task(root)

    a, b = run_pair(runner, task, model_a="cheap", model_b="strong")

    # 1. 两个 EvalResult 都落 JSONL
    assert a.model_tier == "cheap"
    assert b.model_tier == "strong"
    assert a.cost_usd == 0.013
    assert b.cost_usd == 0.087
    assert a.pass_status == PASS_PASSED
    assert b.pass_status == PASS_PASSED

    # 2. JSONL 持久化
    runs = list_runs(base=base, limit=10)
    assert {r.run_id for r in runs} == {a.run_id, b.run_id}
    # load_run 能找回
    assert load_run(a.run_id, base=base) is not None

    # 3. 报告落盘
    md_p = write_report(a, b, base=base)
    json_p = write_report_json(a, b, base=base)
    assert md_p.exists()
    assert json_p.exists()
    md = md_p.read_text("utf-8")
    assert "A/B Eval Report" in md
    assert "bug_fix_001_off_by_one" in md
    assert "Pass winner" in md
    assert "Cost winner" in md
    # Cost winner 应该是 cheap(cost 更低)
    assert "**Cost winner**: `a`" in md
    # 验证
    data = json.loads(json_p.read_text("utf-8"))
    assert data["winner_cost"] == "a"
    assert data["winner_pass"] in ("a", "b", "tie")

    # 4. summary 算 pass rate
    s = summary(base=base, since_days=30)
    assert s["cheap"]["bug_fix"]["passed"] == 1
    assert s["strong"]["bug_fix"]["passed"] == 1


def test_e2e_passing_task_recorded_as_passed(tmp_path, monkeypatch):
    root = tmp_path / "corpus"
    write_seed_corpus(root)
    monkeypatch.setenv("ARGOS_EVAL_CORPUS_DIR", str(root))
    base = tmp_path / "eval"
    wt = FakeWorktree(base / "wt")
    runner = EvalRunner(worktree=wt, base_dir=base, loop_factory=make_fake_loop_factory(make_fake_loop()))
    task = _make_task(root)
    r = runner.run(task, model_tier="cheap")
    assert r.pass_status == PASS_PASSED
    from argos.eval.results import append
    append(r, base=base)
    loaded = load_run(r.run_id, base=base)
    assert loaded is not None
    assert loaded.pass_status == PASS_PASSED


def test_e2e_failing_task_recorded_as_failed(tmp_path, monkeypatch):
    root = tmp_path / "corpus"
    write_seed_corpus(root)
    monkeypatch.setenv("ARGOS_EVAL_CORPUS_DIR", str(root))
    base = tmp_path / "eval"
    wt = FakeWorktree(base / "wt")
    runner = EvalRunner(
        worktree=wt, base_dir=base,
        loop_factory=make_fake_loop_factory(make_fake_loop(verdict=PASS_FAILED, detail="1 failed")),
    )
    task = _make_task(root)
    r = runner.run(task, model_tier="cheap")
    assert r.pass_status == PASS_FAILED
    assert "1 failed" in r.verify_detail


def test_e2e_report_file_created_with_pass_rate(tmp_path, monkeypatch):
    """报告含 pass_rate 字段信息(通过 markdown 表格透出 cost_usd / duration_s 等)。"""
    root = tmp_path / "corpus"
    write_seed_corpus(root)
    monkeypatch.setenv("ARGOS_EVAL_CORPUS_DIR", str(root))
    monkeypatch.setattr(Path, "home", lambda: tmp_path)

    base = tmp_path / "eval"
    wt = FakeWorktree(base / "wt")
    loop_cheap = make_fake_loop(verdict=PASS_PASSED, cost_usd=0.013, tokens_in=1000, tokens_out=500)
    loop_strong = make_fake_loop(verdict=PASS_PASSED, cost_usd=0.087, tokens_in=5000, tokens_out=2000)
    def factory(model_tier: str):
        return loop_cheap if model_tier == "cheap" else loop_strong
    runner = EvalRunner(worktree=wt, base_dir=base, loop_factory=factory)
    task = _make_task(root)
    a, b = run_pair(runner, task, model_a="cheap", model_b="strong")
    md_p = write_report(a, b, base=base)
    md = md_p.read_text("utf-8")
    # 必含字段
    for field in ("pass_status", "duration_s", "tokens_in", "tokens_out",
                  "cost_usd", "steps", "tampered"):
        assert f"| {field}" in md
    # verify_cmd output 段
    assert "verify_cmd output" in md
    # Goal 段
    assert "## Goal" in md


def test_e2e_all_14_corpus_tasks_loadable(tmp_path, monkeypatch):
    """14 个种子任务全部能 load_task + 落 corpus_version。"""
    root = tmp_path / "corpus"
    write_seed_corpus(root)
    monkeypatch.setenv("ARGOS_EVAL_CORPUS_DIR", str(root))
    from argos.eval.corpus import list_tasks, load_task, corpus_version
    tasks = list_tasks()
    assert len(tasks) == 14
    for t in tasks:
        loaded = load_task(t.id)
        assert loaded.id == t.id
        assert loaded.verify_cmd  # 不空
    assert corpus_version() == 1
