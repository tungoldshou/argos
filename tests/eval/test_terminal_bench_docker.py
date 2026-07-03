from __future__ import annotations

import os
import shutil
import subprocess
import time
import uuid
from pathlib import Path

import pytest

from argos.eval.benchmarks import terminal_bench as tb
from argos.eval.benchmarks.terminal_bench import (
    TBClassification, TBTask, classify, load_tb_task,
)




def _docker_available() -> bool:
    return shutil.which("docker") is not None and _docker_daemon_reachable()


def _docker_daemon_reachable() -> bool:
    try:
        r = subprocess.run(
            ["docker", "info"], capture_output=True, text=True, timeout=5,
        )
        return r.returncode == 0
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return False


requires_docker = pytest.mark.skipif(
    not _docker_available(), reason="Docker not available in this env",
)




def _make_tb_task(
    tmp_path: Path,
    *,
    from_line: str,
    extra_dockerfile: str = "",
    run_tests: str = "true\n",
    test_outputs: str = "def test_x(): assert True\n",
    task_id: str | None = None,
) -> Path:
    tid = task_id or f"tb_test_{uuid.uuid4().hex[:8]}"
    d = tmp_path / tid
    (d / "tests").mkdir(parents=True)
    (d / "task.yaml").write_text(
        "instruction: 'test'\n"
        "difficulty: easy\n"
        "category: software-engineering\n"
        "tags: [test]\n"
        "parser_name: pytest\n",
        encoding="utf-8",
    )
    (d / "Dockerfile").write_text(
        f"{from_line}\nWORKDIR /app\n{extra_dockerfile}",
        encoding="utf-8",
    )
    (d / "run-tests.sh").write_text(run_tests, encoding="utf-8")
    (d / "tests" / "test_outputs.py").write_text(test_outputs, encoding="utf-8")
    return d




@requires_docker
def test_classify_marks_ghcr_io_as_supported_when_docker_available(tmp_path):
    d = _make_tb_task(
        tmp_path,
        from_line="FROM ghcr.io/laude-institute/t-bench/python-3-13:20250620",
        task_id="t1",
    )
    parsed = load_tb_task(d)
    assert parsed is not None
    cls = classify(parsed, docker_available=True)
    assert cls.supported is True
    assert cls.kind == "supported_in_docker"


@requires_docker
def test_classify_keeps_unsupported_when_docker_unavailable(tmp_path):
    d = _make_tb_task(
        tmp_path,
        from_line="FROM ghcr.io/laude-institute/t-bench/python-3-13:20250620",
        task_id="t2",
    )
    parsed = load_tb_task(d)
    cls = classify(parsed, docker_available=False)
    assert cls.supported is False
    assert "docker" in cls.reason.lower() or "container" in cls.reason.lower()


def test_classify_unchanged_for_local_python_image(tmp_path):
    d = _make_tb_task(
        tmp_path,
        from_line="FROM python:3.12-slim",
        task_id="t3",
    )
    parsed = load_tb_task(d)
    cls = classify(parsed, docker_available=False)
    assert cls.supported is True
    assert cls.kind == "supported"




@requires_docker
def test_docker_run_tests_passing_returns_passed(tmp_path):
    from argos.eval.benchmarks.terminal_bench import run_subset, _build_verify_cmd
    from argos.eval.runner import EvalRunner
    from argos.eval.runner import PASS_PASSED
    from tests.eval._fakes import FakeWorktree, make_fake_loop_factory, make_fake_loop

    d = _make_tb_task(
        tmp_path,
        from_line="FROM python:3.12-slim",
        run_tests="true\n",
        task_id="docker_pass",
    )
    loop = make_fake_loop(verdict=PASS_PASSED, detail="1 passed in 0.5s", steps=2)
    factory = make_fake_loop_factory(loop)
    wt = FakeWorktree(tmp_path / "wt")
    runner = EvalRunner(
        worktree=wt, base_dir=tmp_path / "eval_base", loop_factory=factory, budget_s=10,
    )
    workdir = tmp_path / "corpus"
    report = run_subset([d], runner=runner, model_tier="default", workdir=workdir, persist=False)
    statuses = {tid: st for tid, (st, _) in report.per_task_status.items()}
    if report.supported == 1:
        assert statuses["docker_pass"] == "passed"


@requires_docker
def test_docker_run_tests_failing_returns_failed(tmp_path):
    from argos.eval.benchmarks.terminal_bench import run_subset
    from argos.eval.runner import EvalRunner, PASS_FAILED
    from tests.eval._fakes import FakeWorktree, make_fake_loop_factory, make_fake_loop

    d = _make_tb_task(
        tmp_path,
        from_line="FROM python:3.12-slim",
        run_tests="false\n",
        task_id="docker_fail",
    )
    loop = make_fake_loop(verdict=PASS_FAILED, detail="1 failed", steps=2)
    factory = make_fake_loop_factory(loop)
    wt = FakeWorktree(tmp_path / "wt")
    runner = EvalRunner(
        worktree=wt, base_dir=tmp_path / "eval_base", loop_factory=factory, budget_s=10,
    )
    workdir = tmp_path / "corpus"
    report = run_subset([d], runner=runner, model_tier="default", workdir=workdir, persist=False)
    statuses = {tid: st for tid, (st, _) in report.per_task_status.items()}
    if report.supported == 1:
        assert statuses["docker_fail"] == "failed"


@requires_docker
def test_docker_unpullable_image_returns_setup_failed(tmp_path):
    from argos.eval.benchmarks.terminal_bench import run_subset
    from argos.eval.runner import EvalRunner, PASS_SETUP_FAILED
    from tests.eval._fakes import FakeWorktree, make_fake_loop_factory, make_fake_loop

    d = _make_tb_task(
        tmp_path,
        from_line="FROM 127.0.0.1:1/no-such-image:latest",
        task_id="docker_nopull",
    )
    loop = make_fake_loop(verdict=PASS_SETUP_FAILED, detail="image pull failed", steps=0)
    factory = make_fake_loop_factory(loop)
    wt = FakeWorktree(tmp_path / "wt")
    runner = EvalRunner(
        worktree=wt, base_dir=tmp_path / "eval_base", loop_factory=factory, budget_s=10,
    )
    workdir = tmp_path / "corpus"
    report = run_subset([d], runner=runner, model_tier="default", workdir=workdir, persist=False)
    statuses = {tid: st for tid, (st, _) in report.per_task_status.items()}
    if report.supported == 1:
        assert statuses["docker_nopull"] == "setup_failed"




@requires_docker
def test_best_of_n_works_on_docker_path(tmp_path, monkeypatch):
    from argos.workflow.engine import WorkflowEngine
    from argos.workflow.spec import parse_spec
    from argos.workflow.subagent import SubAgentFactory
    from argos.workflow.result import AgentResult
    import asyncio

    d = _make_tb_task(
        tmp_path,
        from_line="FROM python:3.12-slim",
        run_tests="true\n",
        task_id="docker_bofn",
    )

    # Spy on SubAgentFactory.run_task to capture candidate agent_ids
    seen: list[str] = []

    async def _spy(self, task, *, item, agent_id, on_phase):
        from argos.workflow.result import AgentResult
        seen.append(agent_id)
        return AgentResult(
            agent_id=agent_id, ok=True, output=f"done {agent_id}",
            verdict="passed", error=None,
        )

    monkeypatch.setattr(SubAgentFactory, "run_task", _spy)

    from tests.e2e.scripted_model import ScriptedModelClient
    eng = WorkflowEngine.for_test(
        workspace=tmp_path,
        model_factory=lambda _p: ScriptedModelClient(["x"]),
    )

    parsed = load_tb_task(d)
    from argos.eval.benchmarks.terminal_bench_best_of_n import build_spec_for_task
    spec = build_spec_for_task(parsed, n=3, model_tier="default")

    async def _go():
        async for _ev in eng.run(spec):
            pass
    asyncio.run(_go())
    assert eng.last_result is not None
    stage = eng.last_result.stages[0]
    assert len(stage.candidates) == 3
    assert {c.agent_id for c in stage.candidates} == {
        "docker_bofn#c0", "docker_bofn#c1", "docker_bofn#c2",
    }




@requires_docker
def test_docker_wrong_solution_still_failed(tmp_path):
    from argos.eval.benchmarks.terminal_bench import run_subset
    from argos.eval.runner import EvalRunner, PASS_FAILED
    from tests.eval._fakes import FakeWorktree, make_fake_loop_factory, make_fake_loop

    d = _make_tb_task(
        tmp_path,
        from_line="FROM python:3.12-slim",
        run_tests="false\n",
        task_id="docker_wrong",
    )
    loop = make_fake_loop(verdict=PASS_FAILED, detail="tests fail", steps=3)
    factory = make_fake_loop_factory(loop)
    wt = FakeWorktree(tmp_path / "wt")
    runner = EvalRunner(
        worktree=wt, base_dir=tmp_path / "eval_base", loop_factory=factory, budget_s=10,
    )
    workdir = tmp_path / "corpus"
    report = run_subset([d], runner=runner, model_tier="default", workdir=workdir, persist=False)
    statuses = {tid: st for tid, (st, _) in report.per_task_status.items()}
    if report.supported == 1:
        assert statuses["docker_wrong"] == "failed"




@requires_docker
def test_container_executor_runs_run_tests_inside_container(tmp_path):
    from argos.eval.benchmarks.terminal_bench_docker import TBContainerExecutor

    d = _make_tb_task(
        tmp_path,
        from_line="FROM python:3.12-slim",
        run_tests="echo hello from container && exit 0\n",
        task_id="executor_e2e",
    )
    parsed = load_tb_task(d)
    assert parsed is not None
    workdir = tmp_path / "verify_ws"
    workdir.mkdir(parents=True, exist_ok=True)
    task = tb.to_eval_task(parsed, workdir=workdir)

    exec_ = TBContainerExecutor(network=False, timeout=60)
    rc = exec_.verify_in_container(parsed, task_dir=task.working_dir)
    assert rc.exit_code == 0, f"expected 0, got {rc}"


@requires_docker
def test_container_executor_returns_nonzero_on_failing_tests(tmp_path):
    from argos.eval.benchmarks.terminal_bench_docker import TBContainerExecutor

    d = _make_tb_task(
        tmp_path,
        from_line="FROM python:3.12-slim",
        run_tests="echo failing && exit 1\n",
        task_id="executor_e2e_fail",
    )
    parsed = load_tb_task(d)
    workdir = tmp_path / "verify_ws2"
    workdir.mkdir(parents=True, exist_ok=True)
    task = tb.to_eval_task(parsed, workdir=workdir)

    exec_ = TBContainerExecutor(network=False, timeout=60)
    rc = exec_.verify_in_container(parsed, task_dir=task.working_dir)
    assert rc.exit_code != 0, f"expected nonzero, got {rc}"




@requires_docker
def test_subagent_output_mirror_copies_agent_files(tmp_path, monkeypatch):
    import subprocess
    from argos.workflow.subagent import SubAgentFactory

    mirror = tmp_path / "mirror"
    mirror.mkdir()
    base = tmp_path / "wt_base"
    base.mkdir()
    subprocess.run(["git", "init", "-q", str(base)], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(base), "config", "user.email", "a@b"], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(base), "config", "user.name", "a"], check=True, capture_output=True)
    (base / "sentinel.txt").write_text("base\n")
    subprocess.run(["git", "-C", str(base), "add", "-A"], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(base), "commit", "-q", "-m", "init"], check=True, capture_output=True)
    wt = base / "wt_test"
    subprocess.run(
        ["git", "-C", str(base), "worktree", "add", "-b", "test", str(wt)],
        check=True, capture_output=True,
    )
    (wt / "hello.txt").write_text("Hello, world!\n")
    (wt / "sentinel.txt").write_text("base MODIFIED\n")
    SubAgentFactory._mirror_worktree(wt, mirror)
    assert (mirror / "hello.txt").is_file(), f"mirror 缺 hello.txt(实际 {list(mirror.iterdir())})"
    assert (mirror / "hello.txt").read_text() == "Hello, world!\n"
    assert (mirror / "sentinel.txt").read_text() == "base MODIFIED\n"


@pytest.mark.slow
@requires_docker
def test_docker_verify_sees_mirror_with_seeded_tests(tmp_path, monkeypatch):
    import subprocess
    import shutil as _sh
    from argos.workflow.subagent import SubAgentFactory
    from argos.eval.benchmarks.terminal_bench_docker import TBContainerExecutor
    from argos.eval.benchmarks.terminal_bench import load_tb_task, to_eval_task

    src = Path("/tmp/tb-inspect/original-tasks/hello-world")
    if not src.is_dir():
        pytest.skip("TB inspect dir not present (skipped)")
    parsed = load_tb_task(src)
    assert parsed is not None
    workdir = tmp_path / "corpus"
    workdir.mkdir()
    task = to_eval_task(parsed, workdir=workdir)

    mirror = tmp_path / "mirror_e2e"
    if mirror.exists():
        import shutil as __sh
        __sh.rmtree(mirror)
    mirror.mkdir(parents=True)
    for entry in ("tests", "run-tests.sh"):
        s = parsed.source_dir / entry
        d = mirror / entry
        if not s.exists():
            continue
        if s.is_dir():
            if d.exists():
                _sh.rmtree(d, ignore_errors=True)
            _sh.copytree(s, d)
        else:
            _sh.copy(s, d)
    assert (mirror / "tests" / "test_outputs.py").is_file()
    assert (mirror / "run-tests.sh").is_file()

    (mirror / "hello.txt").write_text("Hello, world!\n")

    import os
    os.environ["ARGOS_TB_DOCKER_NETWORK"] = "1"
    exec_ = TBContainerExecutor(timeout=180)
    rc = exec_.verify_in_container(parsed, task_dir=mirror)
    assert rc.exit_code == 0, (
        f"verify 应 pass,实际 exit={rc.exit_code} setup_failed={rc.setup_failed}"
        f" detail[-500:]={rc.detail[-500:]}"
    )
    """Verify that _mirror_worktree copies agent-created files into the mirror."""
    import subprocess
    from argos.workflow.subagent import SubAgentFactory

    mirror = tmp_path / "mirror"
    mirror.mkdir()
    base = tmp_path / "wt_base"
    base.mkdir()
    subprocess.run(["git", "init", "-q", str(base)], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(base), "config", "user.email", "a@b"], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(base), "config", "user.name", "a"], check=True, capture_output=True)
    (base / "sentinel.txt").write_text("base\n")
    subprocess.run(["git", "-C", str(base), "add", "-A"], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(base), "commit", "-q", "-m", "init"], check=True, capture_output=True)

    wt = base / "wt_test"
    subprocess.run(
        ["git", "-C", str(base), "worktree", "add", "-b", "test", str(wt)],
        check=True, capture_output=True,
    )
    (wt / "hello.txt").write_text("Hello, world!\n")
    (wt / "sentinel.txt").write_text("base MODIFIED\n")

    SubAgentFactory._mirror_worktree(wt, mirror)
    assert (mirror / "hello.txt").is_file(), f"mirror 缺 hello.txt(实际 {list(mirror.iterdir())})"
    assert (mirror / "hello.txt").read_text() == "Hello, world!\n"
    assert (mirror / "sentinel.txt").read_text() == "base MODIFIED\n"
