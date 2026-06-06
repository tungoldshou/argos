"""#7 T5 A/B 对比 + 报告生成器测试。"""
from __future__ import annotations

import time
from pathlib import Path

import pytest

from argos_agent.eval.compare import (
    generate_report, run_pair, write_report, write_report_json,
    _winner_pass, _winner_cost,
)
from argos_agent.eval.results import list_runs, load_run
from argos_agent.eval.runner import (
    EvalResult, EvalRunner, PASS_PASSED, PASS_FAILED,
)
from argos_agent.eval.corpus import EvalTask

from tests.eval._fakes import FakeWorktree, make_fake_loop, make_fake_loop_factory


# ── helpers ───────────────────────────────────────────────────────────


def _make_result(
    *, run_id: str = "abc123def456", task_id: str = "bug_fix_001_off_by_one",
    model_tier: str = "cheap", pass_status: str = PASS_PASSED,
    cost_usd: float | None = 0.013, **overrides,
) -> EvalResult:
    now = time.time()
    base = dict(
        task_id=task_id, run_id=run_id, model_tier=model_tier,
        started_at=now, finished_at=now, duration_s=120.0,
        pass_status=pass_status, verify_cmd="pytest -q",
        verify_detail="5 passed in 0.5s", tampered=(),
        tokens_in=1000, tokens_out=500, cost_usd=cost_usd, steps=10,
        worktree_path="/tmp/eval/wt/abc", isolation_fallback=None,
        error=None, corpus_version=1, goal="fix the thing",
    )
    base.update(overrides)
    return EvalResult(**base)


# ── run_pair ──────────────────────────────────────────────────────────


def test_run_pair_runs_both_models(tmp_path):
    base = tmp_path / "eval"
    wt = FakeWorktree(base / "wt")
    loop_cheap = make_fake_loop(verdict=PASS_PASSED, cost_usd=0.013, tokens_in=1000, tokens_out=500)
    loop_strong = make_fake_loop(verdict=PASS_PASSED, cost_usd=0.087, tokens_in=5000, tokens_out=2000)
    # 改 fake factory:不同 model_tier 返不同 loop
    def factory(model_tier: str):
        return loop_cheap if model_tier == "cheap" else loop_strong
    runner = EvalRunner(worktree=wt, base_dir=base, loop_factory=factory)
    task = EvalTask(
        id="bug_fix_001", category="bug_fix", difficulty="easy", title="x",
        goal="g", verify_cmd="true", setup_cmd=None, expected_files=(),
        working_dir=tmp_path / "src", corpus_version=1,
    )
    a, b = run_pair(runner, task, model_a="cheap", model_b="strong")
    assert a.model_tier == "cheap"
    assert b.model_tier == "strong"
    assert a.cost_usd == 0.013
    assert b.cost_usd == 0.087


def test_run_pair_appends_both_to_jsonl(tmp_path):
    base = tmp_path / "eval"
    wt = FakeWorktree(base / "wt")
    loop = make_fake_loop()
    runner = EvalRunner(worktree=wt, base_dir=base, loop_factory=make_fake_loop_factory(loop))
    task = EvalTask(
        id="bug_fix_001", category="bug_fix", difficulty="easy", title="x",
        goal="g", verify_cmd="true", setup_cmd=None, expected_files=(),
        working_dir=tmp_path / "src", corpus_version=1,
    )
    a, b = run_pair(runner, task, model_a="cheap", model_b="strong")
    runs = list_runs(base=base)
    assert {r.run_id for r in runs} == {a.run_id, b.run_id}


# ── generate_report ──────────────────────────────────────────────────


def test_generate_report_includes_all_fields():
    a = _make_result(run_id="a111a111a11", model_tier="cheap", cost_usd=0.013)
    b = _make_result(run_id="b222b222b22", model_tier="strong", cost_usd=0.087)
    md = generate_report(a, b)
    for field in ("pass_status", "duration_s", "tokens_in", "tokens_out",
                  "cost_usd", "steps", "tampered", "worktree",
                  "Pass winner", "Cost winner", "Goal",
                  "verify_cmd output"):
        assert field in md


def test_generate_report_picks_pass_winner_when_a_passes_b_fails():
    a = _make_result(pass_status=PASS_PASSED)
    b = _make_result(pass_status=PASS_FAILED)
    assert _winner_pass(a, b) == "a"
    md = generate_report(a, b)
    assert "Pass winner**" in md
    assert "`a`" in md


def test_generate_report_picks_pass_winner_when_b_passes_a_fails():
    a = _make_result(pass_status=PASS_FAILED)
    b = _make_result(pass_status=PASS_PASSED)
    assert _winner_pass(a, b) == "b"
    md = generate_report(a, b)
    assert "Pass winner**" in md
    assert "`b`" in md


def test_generate_report_picks_pass_winner_tie():
    a = _make_result(pass_status=PASS_PASSED)
    b = _make_result(pass_status=PASS_PASSED)
    assert _winner_pass(a, b) == "tie"


def test_generate_report_picks_cost_winner():
    a = _make_result(cost_usd=0.01)
    b = _make_result(cost_usd=0.10)
    assert _winner_cost(a, b) == "a"
    md = generate_report(a, b)
    assert "Cost winner**" in md
    assert "`a`" in md


def test_generate_report_handles_none_cost():
    a = _make_result(cost_usd=None)
    b = _make_result(cost_usd=0.05)
    assert _winner_cost(a, b) == "b"  # b 有 cost,b 赢
    md = generate_report(a, b)
    assert "$N/A" in md


def test_generate_report_handles_both_none_cost():
    a = _make_result(cost_usd=None)
    b = _make_result(cost_usd=None)
    assert _winner_cost(a, b) == "unknown"


def test_generate_report_includes_goal():
    a = _make_result(goal="修复 median 函数的 off-by-one")
    b = _make_result()
    md = generate_report(a, b)
    assert "修复 median 函数的 off-by-one" in md


def test_generate_report_includes_verify_details():
    a = _make_result(verify_detail="5 passed in 0.5s")
    b = _make_result(verify_detail="1 failed: test_x")
    md = generate_report(a, b)
    assert "5 passed in 0.5s" in md
    assert "1 failed: test_x" in md


# ── write_report ─────────────────────────────────────────────────────


def test_write_report_creates_file(tmp_path):
    a = _make_result()
    b = _make_result()
    p = write_report(a, b, base=tmp_path)
    assert p.exists()
    text = p.read_text("utf-8")
    assert "A/B Eval Report" in text


def test_write_report_filename_format(tmp_path):
    a = _make_result(task_id="refactor_001_extract_helper")
    b = _make_result(task_id="refactor_001_extract_helper")
    p = write_report(a, b, base=tmp_path)
    name = p.name
    assert name.startswith("ab-refactor_001_extract_helper-")
    assert name.endswith(".md")


# ── write_report_json ────────────────────────────────────────────────


def test_write_report_json_machine_readable(tmp_path):
    a = _make_result()
    b = _make_result()
    p = write_report_json(a, b, base=tmp_path)
    import json
    data = json.loads(p.read_text("utf-8"))
    assert data["task_id"] == a.task_id
    assert "a" in data and "b" in data
    assert data["winner_pass"] in ("a", "b", "tie")
    assert data["winner_cost"] in ("a", "b", "tie", "unknown")


# ── 失败模式 ──────────────────────────────────────────────────────────


def test_run_pair_first_crash_still_runs_second(tmp_path):
    """第一遍崩 → runner 返 error EvalResult;第二遍仍跑(spec §5.4 失败兜底)。"""
    base = tmp_path / "eval"
    wt = FakeWorktree(base / "wt")
    loop_crash = make_fake_loop(raise_on_run=True)
    loop_ok = make_fake_loop()
    def factory(model_tier: str):
        return loop_crash if model_tier == "cheap" else loop_ok
    runner = EvalRunner(worktree=wt, base_dir=base, loop_factory=factory)
    task = EvalTask(
        id="bug_fix_001", category="bug_fix", difficulty="easy", title="x",
        goal="g", verify_cmd="true", setup_cmd=None, expected_files=(),
        working_dir=tmp_path / "src", corpus_version=1,
    )
    a, b = run_pair(runner, task, model_a="cheap", model_b="strong")
    assert a.pass_status == "error"
    assert b.pass_status == PASS_PASSED
