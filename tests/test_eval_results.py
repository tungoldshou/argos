"""#7 T4 Result JSONL 持久化测试。"""
from __future__ import annotations

import time
from pathlib import Path

import pytest

from argos.eval.results import append, list_runs, load_run, summary
from argos.eval.runner import EvalResult, PASS_PASSED, PASS_FAILED


def _make_result(*, run_id: str = "abc123def456", task_id: str = "bug_fix_001_off_by_one",
                 model_tier: str = "cheap", pass_status: str = PASS_PASSED,
                 finished_at: float | None = None,
                 cost_usd: float | None = 0.013, **overrides) -> EvalResult:
    base = dict(
        task_id=task_id, run_id=run_id, model_tier=model_tier,
        started_at=finished_at or time.time(), finished_at=finished_at or time.time(),
        duration_s=120.0, pass_status=pass_status,
        verify_cmd="python3 -m pytest -q", verify_detail="5 passed in 0.5s",
        tampered=(), tokens_in=1000, tokens_out=500, cost_usd=cost_usd, steps=10,
        worktree_path="/tmp/eval/wt/abc", isolation_fallback=None,
        error=None, corpus_version=1, goal="do the thing",
    )
    base.update(overrides)
    return EvalResult(**base)


# ── append ────────────────────────────────────────────────────────────


def test_append_creates_date_dir(tmp_path):
    r = _make_result()
    append(r, base=tmp_path)
    today = time.strftime("%Y-%m-%d", time.localtime(r.finished_at))
    assert (tmp_path / "runs" / today).is_dir()


def test_append_writes_single_jsonl_line(tmp_path):
    r = _make_result(run_id="xyz789xyz789")
    append(r, base=tmp_path)
    today = time.strftime("%Y-%m-%d", time.localtime(r.finished_at))
    p = tmp_path / "runs" / today / "xyz789xyz789.jsonl"
    assert p.is_file()
    text = p.read_text("utf-8")
    assert text.count("\n") == 1
    assert "bug_fix_001_off_by_one" in text


def test_append_two_results_two_files(tmp_path):
    append(_make_result(run_id="aaa111aaa111"), base=tmp_path)
    append(_make_result(run_id="bbb222bbb222"), base=tmp_path)
    runs = list_runs(base=tmp_path)
    ids = {r.run_id for r in runs}
    assert ids == {"aaa111aaa111", "bbb222bbb222"}


# ── list_runs ─────────────────────────────────────────────────────────


def test_list_runs_returns_in_reverse_date_order(tmp_path):
    # 造 2 个不同日期的 run
    r_old = _make_result(run_id="old111old111", finished_at=time.time() - 3 * 86400)
    r_new = _make_result(run_id="new222new222", finished_at=time.time())
    append(r_old, base=tmp_path)
    append(r_new, base=tmp_path)
    runs = list_runs(base=tmp_path)
    assert runs[0].run_id == "new222new222"
    assert runs[1].run_id == "old111old111"


def test_list_runs_limit_truncates(tmp_path):
    for i in range(5):
        append(_make_result(run_id=f"r{i:09d}0a"), base=tmp_path)
    runs = list_runs(base=tmp_path, limit=3)
    assert len(runs) == 3


def test_list_runs_filter_by_date(tmp_path):
    r_today = _make_result(run_id="t11111111111", finished_at=time.time())
    r_old = _make_result(run_id="o22222222222", finished_at=time.time() - 5 * 86400)
    append(r_today, base=tmp_path)
    append(r_old, base=tmp_path)
    today = time.strftime("%Y-%m-%d", time.localtime(r_today.finished_at))
    runs = list_runs(base=tmp_path, date=today)
    assert len(runs) == 1
    assert runs[0].run_id == "t11111111111"


def test_list_runs_empty_when_no_runs_dir(tmp_path):
    assert list_runs(base=tmp_path) == []


# ── load_run ──────────────────────────────────────────────────────────


def test_load_run_round_trip(tmp_path):
    r = _make_result(run_id="rt1111rt1111", cost_usd=0.987, pass_status=PASS_FAILED)
    append(r, base=tmp_path)
    loaded = load_run("rt1111rt1111", base=tmp_path)
    assert loaded is not None
    assert loaded.run_id == "rt1111rt1111"
    assert loaded.cost_usd == 0.987
    assert loaded.pass_status == PASS_FAILED


def test_load_run_missing_returns_none(tmp_path):
    append(_make_result(run_id="real111real1"), base=tmp_path)
    assert load_run("nonexistent_id_zz", base=tmp_path) is None


def test_load_run_missing_dir_returns_none(tmp_path):
    assert load_run("any_id", base=tmp_path) is None


# ── summary ───────────────────────────────────────────────────────────


def test_summary_aggregates_per_model_per_category(tmp_path):
    now = time.time()
    append(_make_result(run_id="a111a111a11", model_tier="cheap",
                        task_id="bug_fix_001_off_by_one", pass_status=PASS_PASSED, finished_at=now), base=tmp_path)
    append(_make_result(run_id="b222b222b22", model_tier="cheap",
                        task_id="bug_fix_001_off_by_one", pass_status=PASS_FAILED, finished_at=now), base=tmp_path)
    append(_make_result(run_id="c333c333c33", model_tier="strong",
                        task_id="refactor_001_extract_helper", pass_status=PASS_PASSED, finished_at=now), base=tmp_path)
    s = summary(base=tmp_path, since_days=30)
    assert s["cheap"]["bug_fix"]["passed"] == 1
    assert s["cheap"]["bug_fix"]["total"] == 2
    assert s["cheap"]["bug_fix"]["pass_rate"] == 0.5
    assert s["strong"]["refactor"]["passed"] == 1
    assert s["strong"]["refactor"]["total"] == 1


def test_summary_only_includes_past_n_days(tmp_path):
    now = time.time()
    append(_make_result(run_id="r1r1r1r1r11", finished_at=now - 10 * 86400), base=tmp_path)  # 10 天前
    append(_make_result(run_id="r2r2r2r2r22", finished_at=now), base=tmp_path)
    s = summary(base=tmp_path, since_days=7)
    # r1 已被 since=7 过滤;r2 留下
    assert s == {"cheap": {"bug_fix": {"passed": 1, "total": 1, "pass_rate": 1.0}}}


def test_summary_excludes_old_with_strict_window(tmp_path):
    now = time.time()
    append(_make_result(run_id="r1r1r1r1r11", finished_at=now - 10 * 86400), base=tmp_path)
    s = summary(base=tmp_path, since_days=7)
    # 严格 since_days=7 → r1 不在窗口内
    assert s == {}


def test_summary_empty_returns_empty_dict(tmp_path):
    assert summary(base=tmp_path) == {}


# ── 容错 ─────────────────────────────────────────────────────────────


def test_corrupt_jsonl_line_skipped(tmp_path):
    """坏 JSONL 行 → 跳过,不影响其他行。"""
    r = _make_result(run_id="good1good1g")
    append(r, base=tmp_path)
    # 手注坏行
    today = time.strftime("%Y-%m-%d", time.localtime(r.finished_at))
    p = tmp_path / "runs" / today / "good1good1g.jsonl"
    with p.open("a", encoding="utf-8") as fh:
        fh.write("not json\n")
    runs = list_runs(base=tmp_path)
    assert len(runs) == 1
    assert runs[0].run_id == "good1good1g"
