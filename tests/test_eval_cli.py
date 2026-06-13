"""#7 T6 argos eval CLI 子命令测试。"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest


# ── 必备:把 argos/ 注入 sys.path,让 `python -m argos eval ...` 跑通 ─


# ── cmd_list ──────────────────────────────────────────────────────────


def test_eval_list_no_runs_prints_message(capsys, tmp_path, monkeypatch):
    """无 run 跑过 → 友好提示,不假绿。"""
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    from argos.eval import results as _results
    monkeypatch.setattr(_results, "_RUNS_DIR", tmp_path / "eval" / "runs")
    from argos.cli import eval as cli
    rc = cli.cmd_list(_ns(limit=20))
    assert rc == 0
    out = capsys.readouterr().out
    assert "尚未跑过" in out or "corpus" in out


def test_eval_list_with_runs_prints_table(capsys, tmp_path, monkeypatch):
    """落 1 个 result → 表格渲出。"""
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    from argos.eval import results as _results
    monkeypatch.setattr(_results, "_RUNS_DIR", tmp_path / "eval" / "runs")
    from argos.eval.results import append
    from argos.eval.runner import EvalResult, PASS_PASSED
    now = 1717700000.0
    r = EvalResult(
        task_id="bug_fix_001_off_by_one", run_id="abc111abc111",
        model_tier="cheap", started_at=now, finished_at=now, duration_s=120.0,
        pass_status=PASS_PASSED, verify_cmd="pytest -q", verify_detail="ok",
        tampered=(), tokens_in=100, tokens_out=50, cost_usd=0.013, steps=8,
        worktree_path="/tmp", isolation_fallback=None, error=None,
        corpus_version=1, goal="g",
    )
    # append 用 base=tmp_path/"eval"(因为 _runs_dir 在 base 路径下加 /runs)
    # list_runs() 用 monkeypatch 后的 _RUNS_DIR = tmp_path/"eval"/"runs"
    # 两边都指向同一目录
    append(r, base=tmp_path / "eval")
    from argos.cli import eval as cli
    rc = cli.cmd_list(_ns(limit=20))
    assert rc == 0
    out = capsys.readouterr().out
    assert "abc111abc111" in out
    assert "bug_fix_001_off_by_one" in out
    assert "passed" in out


# ── cmd_corpus ────────────────────────────────────────────────────────


def test_eval_corpus_prints_task_list(capsys, tmp_path, monkeypatch):
    from argos.cli import eval as cli
    from tests.eval._seed_corpus import write_seed_corpus
    root = tmp_path / "corpus"
    write_seed_corpus(root)
    monkeypatch.setenv("ARGOS_EVAL_CORPUS_DIR", str(root))
    rc = cli.cmd_corpus(_ns())
    assert rc == 0
    out = capsys.readouterr().out
    assert "corpus version 1" in out
    assert "14 tasks" in out
    assert "bug_fix" in out
    assert "refactor" in out
    assert "test_write" in out
    assert "doc" in out


# ── cmd_run ───────────────────────────────────────────────────────────


def test_eval_run_invokes_runner(capsys, tmp_path, monkeypatch):
    """cmd_run 调 EvalRunner + 落 JSONL + 打印结果。"""
    from argos.cli import eval as cli
    from argos.daemon.worktree import WorktreeManager
    from tests.eval._seed_corpus import write_seed_corpus
    from tests.eval._fakes import FakeWorktree, make_fake_loop_factory, make_fake_loop
    from argos.eval.runner import EvalRunner

    root = tmp_path / "corpus"
    write_seed_corpus(root)
    monkeypatch.setenv("ARGOS_EVAL_CORPUS_DIR", str(root))
    monkeypatch.setattr(Path, "home", lambda: tmp_path)

    loop = make_fake_loop()
    runner = EvalRunner(
        worktree=FakeWorktree(tmp_path / "wt"),
        base_dir=tmp_path / "eval",
        loop_factory=make_fake_loop_factory(loop),
    )
    monkeypatch.setattr(cli, "_make_runner", lambda **kw: runner)

    rc = cli.cmd_run(_ns(task_id="bug_fix_001_off_by_one", model=None, budget=1.0, budget_s=600, keep_worktree=True))
    assert rc == 0
    out = capsys.readouterr().out
    assert "[eval] task=bug_fix_001_off_by_one" in out
    assert "passed" in out
    assert "run_id=" in out


def test_eval_run_unknown_task_raises(capsys, tmp_path, monkeypatch):
    from argos.cli import eval as cli
    rc = cli.cmd_run(_ns(task_id="nonexistent_task_999", model=None, budget=1.0, budget_s=600, keep_worktree=True))
    assert rc == 2
    err = capsys.readouterr().err
    assert "未找到 task" in err


def test_eval_run_returns_nonzero_on_failure(capsys, tmp_path, monkeypatch):
    """弱模型跑挂(setup_failed / failed) → CLI 返非零。"""
    from argos.cli import eval as cli
    from tests.eval._seed_corpus import write_seed_corpus
    from tests.eval._fakes import FakeWorktree, make_fake_loop, make_fake_loop_factory
    from argos.eval.runner import EvalRunner, PASS_FAILED

    root = tmp_path / "corpus"
    write_seed_corpus(root)
    monkeypatch.setenv("ARGOS_EVAL_CORPUS_DIR", str(root))
    monkeypatch.setattr(Path, "home", lambda: tmp_path)

    loop = make_fake_loop(verdict=PASS_FAILED, detail="1 failed")
    runner = EvalRunner(
        worktree=FakeWorktree(tmp_path / "wt"),
        base_dir=tmp_path / "eval",
        loop_factory=make_fake_loop_factory(loop),
    )
    monkeypatch.setattr(cli, "_make_runner", lambda **kw: runner)
    rc = cli.cmd_run(_ns(task_id="bug_fix_001_off_by_one", model=None, budget=1.0, budget_s=600, keep_worktree=True))
    assert rc == 1


# ── cmd_compare ───────────────────────────────────────────────────────


def test_eval_compare_writes_report(capsys, tmp_path, monkeypatch):
    from argos.cli import eval as cli
    from tests.eval._seed_corpus import write_seed_corpus
    from tests.eval._fakes import FakeWorktree, make_fake_loop, make_fake_loop_factory
    from argos.eval.runner import EvalRunner

    root = tmp_path / "corpus"
    write_seed_corpus(root)
    monkeypatch.setenv("ARGOS_EVAL_CORPUS_DIR", str(root))
    monkeypatch.setattr(Path, "home", lambda: tmp_path)

    loop_cheap = make_fake_loop(verdict="passed", cost_usd=0.013)
    loop_strong = make_fake_loop(verdict="passed", cost_usd=0.087)
    def factory(model_tier):
        return loop_cheap if model_tier == "cheap" else loop_strong

    runner = EvalRunner(
        worktree=FakeWorktree(tmp_path / "wt"),
        base_dir=tmp_path / "eval",
        loop_factory=factory,
    )
    monkeypatch.setattr(cli, "_make_runner", lambda **kw: runner)
    rc = cli.cmd_compare(_ns(task_id="bug_fix_001_off_by_one", model_a="cheap", model_b="strong",
                              budget=1.0, budget_s=600, keep_worktree=True))
    assert rc == 0
    out = capsys.readouterr().out
    assert "A/B" in out
    assert "report:" in out
    # 报告落盘(base = Path.home() / ".argos" / "eval",home = tmp_path)
    reports_dir = tmp_path / ".argos" / "eval" / "reports"
    assert reports_dir.exists()
    md_files = list(reports_dir.glob("ab-*.md"))
    assert len(md_files) == 1


# ── subparser 注册 ────────────────────────────────────────────────────


def test_eval_subcommand_registered_in_main(monkeypatch):
    """__main__.py 注册了 eval subparser + list/run/compare/corpus 子命令。"""
    from argos.__main__ import _build_parser
    p = _build_parser()
    # `argos eval --help` 不应崩
    import argparse
    try:
        args = p.parse_args(["eval", "list", "--limit", "10"])
    except SystemExit:
        pytest.fail("eval subparser failed to parse")
    assert args.command == "eval"
    assert args.eval_command == "list"
    assert hasattr(args, "func")


def test_eval_compare_subparser_registers_required_args():
    from argos.__main__ import _build_parser
    p = _build_parser()
    args = p.parse_args(["eval", "compare", "bug_fix_001", "cheap", "strong"])
    assert args.task_id == "bug_fix_001"
    assert args.model_a == "cheap"
    assert args.model_b == "strong"


# ── helpers ───────────────────────────────────────────────────────────


def _ns(**kwargs):
    """构造 argparse.Namespace 的便利 wrapper(只用于直接调 cmd_*,不走 parse_args)。"""
    import argparse
    return argparse.Namespace(**kwargs)
