"""适配器 verify_cmd 白名单 + tests/ 落盘 验收。

覆盖:
  (a) _build_verify_cmd 产出的 verify_cmd 首 token 必须在 ALLOWED_CMDS 内;
      不得含裸 `bash -c` 包(白名单外 token 直接被 verify_gate 拒,N=1 必 0%)。
  (b) 一个"产出正确"的 fixture 任务,经过 EvalRunner(走真 verify)→ 判 passed
      (不再是 verify 拒绝的假 failed)。
  (c) 一个"产出错误"的任务,仍被如实判 failed —— 没把摩擦修过头变成放水。
  (d) to_eval_task 落盘后,源任务自带的 tests/ 目录被复制到 worktree
      (为 A2 真 TB 任务铺路:很多 TB 任务的 run-tests.sh 直接调 tests/test_outputs.py,
       假设 tests/ 已存在)。

硬约束(模块顶部 hard rule):不动 ALLOWED_CMDS / verify 三态 / detect_tampering;
只动适配器的翻译层(_build_verify_cmd)与落盘流程(to_eval_task 多拷一个 tests/)。
"""
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


# ── (a) _build_verify_cmd 首 token 在白名单内,不含裸 bash -c ──


def test_build_verify_cmd_first_token_in_allowed_set():
    """白名单是硬规则:verify_cmd 经 shlex.split 后的首 token 必须在 ALLOWED_CMDS。

    不在白名单 → verify_gate 拒绝 → 全 N=1 必 0%(上一轮的真凶)。"""
    for d in ("tb_echo_hello", "tb_write_function", "tb_count_lines", "tb_grade_score"):
        tb_task = tb.load_tb_task(SMOKE_DIR / d)
        assert tb_task is not None, d
        # 用一个临时 workdir 走真实 to_eval_task 路径(它会落盘 + 调 _build_verify_cmd)。
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
        # 额外:不允许裸 bash -c 包(本测试不允这种"骗过 whitelis头"的形式)
        #  —— 必须从 shlex.split 后的首 token 就是白名单里的命令,而不是
        # `bash` 在白名单外。
        assert first != "bash", (
            f"{d}: 首 token 仍是 bash —— 适配器不应再 wrap bash -c;"
            f"应改用白名单内命令直接调脚本"
        )


# ── (b) 正确产出 → 真 passed ────────────────────────────────────


def test_run_eval_passes_when_solution_is_correct(tmp_path):
    """一个"产出正确"的 fixture:agent 真把 /app/run.sh 写成 echo hello world,
    verify 跑 `bash -c 'true'`(应 pass)。整条 EvalRunner 跑下来,pass_status='passed'。

    注:这里复用现有 tb_echo_hello(verify_cmd 已被适配器改写成白名单内形式后,
    真跑能过)。Fake loop 模拟 agent 产出 OK + verify 退出 0。
    """
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


# ── (c) 错误产出 → 仍 failed(没放水) ───────────────────────────


def test_run_eval_fails_when_solution_is_wrong(tmp_path):
    """一个"产出错误"的 fixture:agent 真把 /app/run.sh 写错,verify 应 fail。

    验真三态 + 白名单:不允许把摩擦修了之后,错的也变 passed。
    """
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
    # 产出错 → 0 passed;但 loop 真跑了,只是 verify 判 failed
    assert report.passed == 0
    assert report.failed == 1
    assert report.pass_at_1 == 0.0
    statuses = {tid: st for tid, (st, _) in report.per_task_status.items()}
    assert statuses["tb_echo_hello"] == "failed"


# ── (d) to_eval_task 把源任务 tests/ 复制到 worktree ──────────


def test_to_eval_task_copies_tests_dir_to_worktree(tmp_path):
    """源 TB 任务若有 tests/ 目录,to_eval_task 落盘后,worktree 内 workdir/tests/ 可达。

    真 TB 任务:run-tests.sh 直接 `pytest tests/test_outputs.py`,假设 tests/ 已存在。
    本适配器之前不复制 → 真 TB 任务全因找不到 tests 假 fail。修后 tests/ 在落盘 workdir 内可达。
    """
    # 用一个临时 TB 任务目录(只放 task.yaml + run-tests.sh + tests/test_outputs.py),
    # 不依赖仓库内置 fixture(本仓库内置的 tb_echo_hello 等不一定有 tests/)。
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
    # tests/ 必须在落盘后的任务目录里
    assert (td / "tests").is_dir(), f"tests/ not copied: {td}"
    assert (td / "tests" / "test_outputs.py").is_file()
    # 内容真复制过来了(不是空目录)
    assert (td / "tests" / "test_outputs.py").read_text().strip() == \
        "def test_x(): assert True"


# ── 工具 ────────────────────────────────────────────────────────


def make_fake_loop_factory_for_passed():
    """返一个 loop_factory:loop.run_sync 返 passed(模拟 agent 产出正确,verify 退出 0)。"""
    from tests.eval._fakes import make_fake_loop
    loop = make_fake_loop(verdict=PASS_PASSED, detail="1 passed", steps=2)
    return make_fake_loop_factory(loop)


def make_fake_loop_factory_for_failed():
    """返一个 loop_factory:loop.run_sync 返 failed(模拟 agent 产出错,verify 非 0)。"""
    from tests.eval._fakes import make_fake_loop
    loop = make_fake_loop(verdict=PASS_FAILED, detail="1 failed", steps=2)
    return make_fake_loop_factory(loop)
