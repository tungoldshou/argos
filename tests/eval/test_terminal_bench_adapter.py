"""Terminal-Bench 适配器测试。

覆盖:
  (a) loader 把一个 TB 任务转成 EvalTask,goal/verify_cmd/setup_cmd 字段对得上
  (b) classifier 标 "unsupported: needs container image" / "unsupported: /protected" / supported
  (c) run_subset 跑小子集 → pass@1 数字 + JSONL + 跳过计入 unsupported 而不进分母

复用 _fakes.FakeWorktree / make_fake_loop(不 mock 沙箱;只是替 loop 桩)。
"""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from argos_agent.eval.benchmarks import terminal_bench as tb
from argos_agent.eval.corpus import EvalTask, load_task
from argos_agent.eval.runner import (
    PASS_ERROR, PASS_FAILED, PASS_PASSED, PASS_SETUP_FAILED,
)

from tests.eval._fakes import FakeWorktree, make_fake_loop, make_fake_loop_factory


SMOKE_DIR = Path(__file__).parent / "_fixtures" / "tb_smoke"


# ── (a) loader:把 TB 任务转 EvalTask ──────────────────────────────


def test_loader_parses_supported_task():
    """tb_echo_hello 有 task.yaml + instruction + run-tests.sh + Dockerfile,应可解析。"""
    src = SMOKE_DIR / "tb_echo_hello"
    parsed = tb.load_tb_task(src)
    assert parsed is not None
    assert parsed.task_id == "tb_echo_hello"
    assert parsed.instruction.startswith("Write a shell script")
    assert parsed.difficulty == "easy"
    assert parsed.category == "software-engineering"
    assert "smoke" in parsed.tags
    assert parsed.has_dockerfile is True
    # run-tests.sh 是个 shell 脚本块
    assert "true" in parsed.run_tests_sh
    # RUN 行至少有 mkdir
    assert any("mkdir" in r for r in parsed.dockerfile_runs)


def test_loader_returns_none_for_missing_yaml(tmp_path):
    """目录里没 task.yaml → None(不爆)。"""
    (tmp_path / "run-tests.sh").write_text("pytest")
    assert tb.load_tb_task(tmp_path) is None


def test_loader_returns_none_for_missing_instruction(tmp_path):
    """task.yaml 没 instruction → None。"""
    (tmp_path / "task.yaml").write_text("difficulty: easy\n")
    (tmp_path / "run-tests.sh").write_text("pytest")
    assert tb.load_tb_task(tmp_path) is None


def test_to_eval_task_writes_goal_verify_setup(tmp_path):
    """to_eval_task 把 TB 任务落成 EvalTask 文件树,字段对得上。"""
    parsed = tb.load_tb_task(SMOKE_DIR / "tb_echo_hello")
    assert parsed is not None
    workdir = tmp_path / "corpus"
    task = tb.to_eval_task(parsed, workdir=workdir)
    # 1. 落盘文件齐全
    td = workdir / parsed.task_id
    assert (td / "goal.md").is_file()
    assert (td / "verify_cmd").is_file()
    assert (td / "setup.sh").is_file()
    assert (td / "category").is_file()
    # 2. 字段
    assert isinstance(task, EvalTask)
    assert task.id == "tb_echo_hello"
    assert "Write a shell script" in task.goal
    # verify_cmd:单行 python -c '...' 包 bash(白名单首 token = python)。
    # 历史:之前是 `bash -c '...'` 首 token = bash → verify_gate 拒,N=1 必 0%。
    # 修后首 token 必须落在 ALLOWED_CMDS 内,适配器不再 wrap bash。
    assert task.verify_cmd.startswith("python -c ")
    # $TEST_DIR 已被替换为 workdir 绝对路径
    assert "$TEST_DIR" not in task.verify_cmd
    # setup_cmd(Dockerfile RUN 行拼成 bash 脚本)非空;具体行内容由 RUN 决定
    assert task.setup_cmd is not None
    assert task.setup_cmd.startswith("#!/usr/bin/env bash")
    assert "mkdir" in task.setup_cmd  # fixture Dockerfile 有 RUN mkdir
    # category 映射:software-engineering → bug_fix
    assert task.category == "bug_fix"
    assert (td / "category").read_text().strip() == "bug_fix"
    # working_dir 指向落盘的 task 子目录
    assert task.working_dir == td


def test_to_eval_task_loads_back_through_corpus_loader(tmp_path, monkeypatch):
    """EvalTask 落盘后能用 corpus.load_task 读回来(对齐现有 corpus 体系)。"""
    monkeypatch.setenv("ARGOS_EVAL_CORPUS_DIR", str(tmp_path / "corpus_root"))
    parsed = tb.load_tb_task(SMOKE_DIR / "tb_echo_hello")
    assert parsed is not None
    workdir = tmp_path / "corpus_root"
    task = tb.to_eval_task(parsed, workdir=workdir)
    # corpus 期望 manifest 在 workdir 顶层;load_task 读 <root>/<task_id>/...
    # 我们把 workdir 自身当 corpus 根,加个最小 manifest 让 corpus_version 不为 0
    (workdir / "corpus.json").write_text(json.dumps({"version": 1, "tasks": [
        {"id": task.id, "title": task.title, "category": task.category, "difficulty": task.difficulty},
    ]}), encoding="utf-8")
    loaded = load_task(task.id, root=workdir)
    assert loaded.id == task.id
    assert loaded.goal == task.goal
    assert loaded.verify_cmd == task.verify_cmd


# ── (b) classifier:supported / unsupported ─────────────────────────


def test_classify_marks_python_base_as_supported():
    """FROM python:3.12 + 有 RUN → supported(v1 适配器可以跑本机有 python 的)。"""
    parsed = tb.load_tb_task(SMOKE_DIR / "tb_echo_hello")
    cls = tb.classify(parsed)
    assert cls.supported is True
    assert cls.kind == "supported"


def test_classify_marks_custom_t_bench_image_unsupported():
    """FROM ghcr.io/laude-institute/t-bench/... → 无 Docker 时判 unsupported_custom_image_no_docker
    (修后:有 Docker 改判 supported_in_docker;测试显式传 docker_available=False
    模拟"没 Docker"场景)。"""
    parsed = tb.load_tb_task(SMOKE_DIR / "tb_compile_asm")
    cls = tb.classify(parsed, docker_available=False)
    assert cls.supported is False
    assert "custom" in cls.kind or "docker" in cls.kind.lower()
    assert "container image" in cls.reason.lower()


def test_classify_marks_protected_path_unsupported():
    """有 /protected/ 目录 → unsupported_protected_path(测试要容器内路径)。"""
    parsed = tb.load_tb_task(SMOKE_DIR / "tb_hidden_state")
    cls = tb.classify(parsed)
    assert cls.supported is False
    assert cls.kind == "unsupported_protected_path"
    assert "/protected" in cls.reason


def test_classify_handles_missing_dockerfile(tmp_path):
    """既没 Dockerfile 也没 RUN → unsupported_no_setup(没东西能跑)。"""
    d = tmp_path / "bare"
    d.mkdir()
    (d / "task.yaml").write_text("instruction: do something\ndifficulty: easy\n")
    (d / "run-tests.sh").write_text("pytest $TEST_DIR/tests/test_outputs.py -rA")
    parsed = tb.load_tb_task(d)
    cls = tb.classify(parsed)
    assert cls.supported is False
    assert cls.kind == "unsupported_no_setup"


# ── (c) run_subset:pass@1 数字 + JSONL + 跳过不入分母 ────────────


def _make_runner(tmp_path, *, verdict, detail="", steps=1):
    """装一个最小 EvalRunner:worktree 用 fake,loop_factory 用 fake_loop。"""
    wt = FakeWorktree(tmp_path / "wt_base")
    loop = make_fake_loop(verdict=verdict, detail=detail, steps=steps)
    factory = make_fake_loop_factory(loop)
    from argos_agent.eval.runner import EvalRunner
    return EvalRunner(worktree=wt, base_dir=tmp_path / "eval_base", loop_factory=factory, budget_s=10)


def test_run_subset_picks_supported_and_skips_unsupported(tmp_path):
    """3 个 smoke 任务:1 supported,2 unsupported(自定义 image + protected)→ pass@1 跑 1 条。
    显式 docker_available=False:让 tb_compile_asm 走老 unsupported 路径(测试"无 Docker"行为)。"""
    runner = _make_runner(tmp_path, verdict=PASS_PASSED, detail="1 passed")
    workdir = tmp_path / "corpus"
    report = tb.run_subset(
        [SMOKE_DIR / "tb_echo_hello", SMOKE_DIR / "tb_compile_asm", SMOKE_DIR / "tb_hidden_state"],
        runner=runner, model_tier="default", workdir=workdir, persist=False,
        docker_available=False,
    )
    # 计数
    assert report.total_seen == 3
    assert report.supported == 1
    assert report.unsupported == 2
    assert report.passed == 1
    # pass@1 = 1 / 1(只算 supported 的)
    assert report.pass_at_1 == 1.0
    # 跳过原因分桶
    assert report.unsupported_reasons.get("unsupported_custom_image_no_docker") == 1
    assert report.unsupported_reasons.get("unsupported_protected_path") == 1
    # per-task 状态:2 跳 + 1 pass
    statuses = {tid: st for tid, (st, _) in report.per_task_status.items()}
    assert statuses["tb_echo_hello"] == "passed"
    assert statuses["tb_compile_asm"] == "skipped"
    assert statuses["tb_hidden_state"] == "skipped"


def test_run_subset_does_not_let_skipped_drag_pass_at_1(tmp_path):
    """5 个 unsupported + 1 failed → pass@1 = 0/1 = 0.0,不是 0/6。
    docker_available=False 模拟"无 Docker"场景。"""
    runner = _make_runner(tmp_path, verdict=PASS_FAILED, detail="1 failed")
    workdir = tmp_path / "corpus"
    # 6 个 unsupported(tb_compile_asm)+ 1 个真跑;不重复传同一 dir,直接传 unsupported
    subset = [SMOKE_DIR / "tb_compile_asm"] * 5 + [SMOKE_DIR / "tb_echo_hello"]
    report = tb.run_subset(
        subset, runner=runner, model_tier="default", workdir=workdir, persist=False,
        docker_available=False,
    )
    assert report.total_seen == 6
    assert report.supported == 1
    assert report.unsupported == 5
    assert report.failed == 1
    # pass@1 = 0 / 1(不把 5 skipped 算进分母)
    assert report.pass_at_1 == 0.0


def test_run_subset_persists_jsonl_for_supported(tmp_path):
    """persist=True(默认)→ supported 跑的应落 JSONL 到 runner.base_dir/runs/。"""
    runner = _make_runner(tmp_path, verdict=PASS_PASSED, detail="1 passed")
    workdir = tmp_path / "corpus"
    tb.run_subset(
        [SMOKE_DIR / "tb_echo_hello"],
        runner=runner, model_tier="default", workdir=workdir, persist=True,
    )
    # 跑 base_dir/runs/<YYYY-MM-DD>/<run_id>.jsonl
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
    """skipped 任务不应落 JSONL(否则统计里会出现一堆跳过的尾巴)。
    docker_available=False 让 tb_compile_asm 走老 skip 路径。"""
    runner = _make_runner(tmp_path, verdict=PASS_PASSED)
    workdir = tmp_path / "corpus"
    tb.run_subset(
        [SMOKE_DIR / "tb_compile_asm"],
        runner=runner, model_tier="default", workdir=workdir, persist=True,
        docker_available=False,
    )
    runs_dir = runner.base_dir / "runs"
    if runs_dir.exists():
        # 不应有文件
        files = list(runs_dir.rglob("*.jsonl"))
        assert files == []
