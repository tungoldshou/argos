"""Internal documentation."""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from argos.eval.benchmarks import terminal_bench as tb
from argos.eval.corpus import EvalTask, load_task
from argos.eval.runner import (
    PASS_ERROR, PASS_FAILED, PASS_PASSED, PASS_SETUP_FAILED,
)

from tests.eval._fakes import FakeWorktree, make_fake_loop, make_fake_loop_factory


SMOKE_DIR = Path(__file__).parent / "_fixtures" / "tb_smoke"




def test_loader_parses_supported_task():
    """Internal documentation."""
    src = SMOKE_DIR / "tb_echo_hello"
    parsed = tb.load_tb_task(src)
    assert parsed is not None
    assert parsed.task_id == "tb_echo_hello"
    assert parsed.instruction.startswith("Write a shell script")
    assert parsed.difficulty == "easy"
    assert parsed.category == "software-engineering"
    assert "smoke" in parsed.tags
    assert parsed.has_dockerfile is True
    assert "true" in parsed.run_tests_sh
    assert any("mkdir" in r for r in parsed.dockerfile_runs)


def test_loader_returns_none_for_missing_yaml(tmp_path):
    """Internal documentation."""
    (tmp_path / "run-tests.sh").write_text("pytest")
    assert tb.load_tb_task(tmp_path) is None


def test_loader_returns_none_for_missing_instruction(tmp_path):
    """Internal documentation."""
    (tmp_path / "task.yaml").write_text("difficulty: easy\n")
    (tmp_path / "run-tests.sh").write_text("pytest")
    assert tb.load_tb_task(tmp_path) is None


def test_to_eval_task_writes_goal_verify_setup(tmp_path):
    """Internal documentation."""
    parsed = tb.load_tb_task(SMOKE_DIR / "tb_echo_hello")
    assert parsed is not None
    workdir = tmp_path / "corpus"
    task = tb.to_eval_task(parsed, workdir=workdir)
    td = workdir / parsed.task_id
    assert (td / "goal.md").is_file()
    assert (td / "verify_cmd").is_file()
    assert (td / "setup.sh").is_file()
    assert (td / "category").is_file()
    assert isinstance(task, EvalTask)
    assert task.id == "tb_echo_hello"
    assert "Write a shell script" in task.goal
    assert task.verify_cmd.startswith("python -c ")
    assert "$TEST_DIR" not in task.verify_cmd
    assert task.setup_cmd is not None
    assert task.setup_cmd.startswith("#!/usr/bin/env bash")
    assert "mkdir" in task.setup_cmd
    assert task.category == "bug_fix"
    assert (td / "category").read_text().strip() == "bug_fix"
    assert task.working_dir == td


def test_to_eval_task_loads_back_through_corpus_loader(tmp_path, monkeypatch):
    """Internal documentation."""
    monkeypatch.setenv("ARGOS_EVAL_CORPUS_DIR", str(tmp_path / "corpus_root"))
    parsed = tb.load_tb_task(SMOKE_DIR / "tb_echo_hello")
    assert parsed is not None
    workdir = tmp_path / "corpus_root"
    task = tb.to_eval_task(parsed, workdir=workdir)
    (workdir / "corpus.json").write_text(json.dumps({"version": 1, "tasks": [
        {"id": task.id, "title": task.title, "category": task.category, "difficulty": task.difficulty},
    ]}), encoding="utf-8")
    loaded = load_task(task.id, root=workdir)
    assert loaded.id == task.id
    assert loaded.goal == task.goal
    assert loaded.verify_cmd == task.verify_cmd


# ── (b) classifier:supported / unsupported ─────────────────────────


def test_classify_marks_python_base_as_supported():
    """Internal documentation."""
    parsed = tb.load_tb_task(SMOKE_DIR / "tb_echo_hello")
    cls = tb.classify(parsed)
    assert cls.supported is True
    assert cls.kind == "supported"


def test_classify_marks_custom_t_bench_image_unsupported():
    """Internal documentation."""
    parsed = tb.load_tb_task(SMOKE_DIR / "tb_compile_asm")
    cls = tb.classify(parsed, docker_available=False)
    assert cls.supported is False
    assert "custom" in cls.kind or "docker" in cls.kind.lower()
    assert "container image" in cls.reason.lower()


def test_classify_marks_protected_path_unsupported():
    """Internal documentation."""
    parsed = tb.load_tb_task(SMOKE_DIR / "tb_hidden_state")
    cls = tb.classify(parsed)
    assert cls.supported is False
    assert cls.kind == "unsupported_protected_path"
    assert "/protected" in cls.reason


def test_classify_handles_missing_dockerfile(tmp_path):
    """Internal documentation."""
    d = tmp_path / "bare"
    d.mkdir()
    (d / "task.yaml").write_text("instruction: do something\ndifficulty: easy\n")
    (d / "run-tests.sh").write_text("pytest $TEST_DIR/tests/test_outputs.py -rA")
    parsed = tb.load_tb_task(d)
    cls = tb.classify(parsed)
    assert cls.supported is False
    assert cls.kind == "unsupported_no_setup"




def _make_runner(tmp_path, *, verdict, detail="", steps=1):
    """Internal documentation."""
    wt = FakeWorktree(tmp_path / "wt_base")
    loop = make_fake_loop(verdict=verdict, detail=detail, steps=steps)
    factory = make_fake_loop_factory(loop)
    from argos.eval.runner import EvalRunner
    return EvalRunner(worktree=wt, base_dir=tmp_path / "eval_base", loop_factory=factory, budget_s=10)


def test_run_subset_picks_supported_and_skips_unsupported(tmp_path):
    """Internal documentation."""
    runner = _make_runner(tmp_path, verdict=PASS_PASSED, detail="1 passed")
    workdir = tmp_path / "corpus"
    report = tb.run_subset(
        [SMOKE_DIR / "tb_echo_hello", SMOKE_DIR / "tb_compile_asm", SMOKE_DIR / "tb_hidden_state"],
        runner=runner, model_tier="default", workdir=workdir, persist=False,
        docker_available=False,
    )
    assert report.total_seen == 3
    assert report.supported == 1
    assert report.unsupported == 2
    assert report.passed == 1
    assert report.pass_at_1 == 1.0
    assert report.unsupported_reasons.get("unsupported_custom_image_no_docker") == 1
    assert report.unsupported_reasons.get("unsupported_protected_path") == 1
    statuses = {tid: st for tid, (st, _) in report.per_task_status.items()}
    assert statuses["tb_echo_hello"] == "passed"
    assert statuses["tb_compile_asm"] == "skipped"
    assert statuses["tb_hidden_state"] == "skipped"


def test_run_subset_does_not_let_skipped_drag_pass_at_1(tmp_path):
    """Internal documentation."""
    runner = _make_runner(tmp_path, verdict=PASS_FAILED, detail="1 failed")
    workdir = tmp_path / "corpus"
    subset = [SMOKE_DIR / "tb_compile_asm"] * 5 + [SMOKE_DIR / "tb_echo_hello"]
    report = tb.run_subset(
        subset, runner=runner, model_tier="default", workdir=workdir, persist=False,
        docker_available=False,
    )
    assert report.total_seen == 6
    assert report.supported == 1
    assert report.unsupported == 5
    assert report.failed == 1
    assert report.pass_at_1 == 0.0


def test_run_subset_persists_jsonl_for_supported(tmp_path):
    """Internal documentation."""
    runner = _make_runner(tmp_path, verdict=PASS_PASSED, detail="1 passed")
    workdir = tmp_path / "corpus"
    tb.run_subset(
        [SMOKE_DIR / "tb_echo_hello"],
        runner=runner, model_tier="default", workdir=workdir, persist=True,
    )
    runs = list((runner.base_dir / "runs").iterdir())
    assert len(runs) == 1
    day_dir = runs[0]
    files = list(day_dir.glob("*.jsonl"))
    assert len(files) == 1
    line = files[0].read_text(encoding="utf-8").strip()
    rec = json.loads(line)
    assert rec["task_id"] == "tb_echo_hello"
    assert rec["pass_status"] == PASS_PASSED
    assert rec["model_tier"] == "default"


def test_run_subset_does_not_persist_for_skipped(tmp_path):
    """Internal documentation."""
    runner = _make_runner(tmp_path, verdict=PASS_PASSED)
    workdir = tmp_path / "corpus"
    tb.run_subset(
        [SMOKE_DIR / "tb_compile_asm"],
        runner=runner, model_tier="default", workdir=workdir, persist=True,
        docker_available=False,
    )
    runs_dir = runner.base_dir / "runs"
    if runs_dir.exists():
        files = list(runs_dir.rglob("*.jsonl"))
        assert files == []


def test_smoke_subset_resolves_to_task_dirs():
    """Internal documentation."""
    subset = tb._resolve_subset_arg("smoke")

    assert subset
    assert all((p / "task.yaml").is_file() for p in subset)
    assert any(p.name == "tb_echo_hello" for p in subset)
    assert all(p.name != "tb_smoke" for p in subset)


def test_smoke_subset_missing_fixture_returns_missing_path(tmp_path, monkeypatch):
    """Internal documentation."""
    missing = tmp_path / "missing_smoke"
    monkeypatch.setattr(tb, "_smoke_subset_dir", lambda: missing)

    assert tb._resolve_subset_arg("smoke") == [missing]
