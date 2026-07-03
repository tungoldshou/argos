from __future__ import annotations

import shlex
import subprocess
from pathlib import Path

import pytest

from argos import runtime
from argos.core.verify_gate import Verifier
from argos.eval.benchmarks import terminal_bench as tb
from argos.tools import ALLOWED_CMDS
from argos.eval.runner import (
    EvalRunner, LoopOutcome, PASS_PASSED, PASS_FAILED, PASS_UNVERIFIABLE,
)
from argos.eval.corpus import EvalTask

from tests.eval._fakes import FakeWorktree, make_fake_loop_factory

SMOKE_DIR = Path(__file__).parent / "_fixtures" / "tb_smoke"




def test_build_verify_cmd_first_token_in_allowed_set():
    for d in ("tb_echo_hello", "tb_write_function", "tb_count_lines", "tb_grade_score"):
        tb_task = tb.load_tb_task(SMOKE_DIR / d)
        assert tb_task is not None, d
        workdir = Path("/tmp/_tb_verify_test") / d
        if workdir.exists():
            import shutil
            shutil.rmtree(workdir, ignore_errors=True)
        task = tb.to_eval_task(tb_task, workdir=workdir)
        parts = shlex.split(task.verify_cmd)
        assert parts, f"{d}: verify_cmd 经 shlex.split 后为空"
        first = Path(parts[0]).name
        assert first in ALLOWED_CMDS, (
            f"{d}: verify_cmd 首 token {first!r} 不在白名单 {sorted(ALLOWED_CMDS)};"
            f" 整条 cmd: {task.verify_cmd!r}"
        )
        assert first != "bash", (
            f"{d}: 首 token 仍是 bash —— 适配器不应再 wrap bash -c;"
            f"应改用白名单内命令直接调脚本"
        )




def test_run_eval_passes_when_solution_is_correct(tmp_path):
    wt = FakeWorktree(tmp_path / "wt_base")
    factory = make_fake_loop_factory_for_passed()
    runner = EvalRunner(
        worktree=wt, base_dir=tmp_path / "eval_base",
        loop_factory=factory, budget_s=10,
    )
    from argos.eval.benchmarks.terminal_bench import run_subset
    workdir = tmp_path / "corpus"
    report = run_subset(
        [SMOKE_DIR / "tb_echo_hello"], runner=runner, model_tier="default",
        workdir=workdir, persist=False,
    )
    assert report.passed == 1
    assert report.pass_at_1 == 1.0
    statuses = {tid: st for tid, (st, _) in report.per_task_status.items()}
    assert statuses["tb_echo_hello"] == "passed"




def test_run_eval_fails_when_solution_is_wrong(tmp_path):
    wt = FakeWorktree(tmp_path / "wt_base")
    factory = make_fake_loop_factory_for_failed()
    runner = EvalRunner(
        worktree=wt, base_dir=tmp_path / "eval_base",
        loop_factory=factory, budget_s=10,
    )
    from argos.eval.benchmarks.terminal_bench import run_subset
    workdir = tmp_path / "corpus"
    report = run_subset(
        [SMOKE_DIR / "tb_echo_hello"], runner=runner, model_tier="default",
        workdir=workdir, persist=False,
    )
    assert report.passed == 0
    assert report.failed == 1
    assert report.pass_at_1 == 0.0
    statuses = {tid: st for tid, (st, _) in report.per_task_status.items()}
    assert statuses["tb_echo_hello"] == "failed"




def test_to_eval_task_copies_tests_dir_to_worktree(tmp_path):
    src = tmp_path / "src_task"
    (src / "tests").mkdir(parents=True)
    (src / "task.yaml").write_text(
        "instruction: test\ndifficulty: easy\ncategory: software-engineering\n",
        encoding="utf-8",
    )
    (src / "run-tests.sh").write_text("true\n", encoding="utf-8")
    (src / "Dockerfile").write_text("FROM python:3.12\n", encoding="utf-8")
    (src / "tests" / "test_outputs.py").write_text("def test_x(): assert True\n", encoding="utf-8")
    parsed = tb.load_tb_task(src)
    assert parsed is not None
    workdir = tmp_path / "corpus"
    task = tb.to_eval_task(parsed, workdir=workdir)
    td = workdir / parsed.task_id
    assert (td / "tests").is_dir(), f"tests/ not copied: {td}"
    assert (td / "tests" / "test_outputs.py").is_file()
    assert (td / "tests" / "test_outputs.py").read_text().strip() ==\
        "def test_x(): assert True"




def make_fake_loop_factory_for_passed():
    from tests.eval._fakes import make_fake_loop
    loop = make_fake_loop(verdict=PASS_PASSED, detail="1 passed", steps=2)
    return make_fake_loop_factory(loop)


def make_fake_loop_factory_for_failed():
    from tests.eval._fakes import make_fake_loop
    loop = make_fake_loop(verdict=PASS_FAILED, detail="1 failed", steps=2)
    return make_fake_loop_factory(loop)
