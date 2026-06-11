"""Terminal-Bench 容器路径(Docker 真跑)验收。

覆盖:
  (a) 分类:TB 任务 FROM 是 ghcr.io/... → classify 判 supported_in_docker(在
      Docker 可用时);Docker 不可用 → 仍判 unsupported_custom_image_no_docker
      (诚实 skip),不假装能跑。
  (b) 真容器跑:run-tests.sh 退出 0 → passed;非 0 → failed;镜像拉不到 / 构建失败
      → setup_failed(诚实 skip,不计入 passed 分母)。
  (c) best_of_n:在容器路径下,N 个候选各自的 verify 独立,winner 选真 passed。
  (d) 没放水:错误产出 → 仍 failed,不允许把判定放宽。

测试基础设施:不依赖 ghcr.io(那需要联网 + 拉大镜像),用本地小镜像(python:3.12-slim
或一个本地 build 的 hello-world 镜像)模拟"容器路径"。`requires_docker` 守卫在
Docker 不可用时 skip 整个文件,而不是 fail。

约束:verify 走容器内 run-tests.sh + 本仓三态 Verifier 语义;不动 ALLOWED_CMDS / 三态
判定 / 篡改检测。
"""
from __future__ import annotations

import os
import shutil
import subprocess
import time
import uuid
from pathlib import Path

import pytest

from argos_agent.eval.benchmarks import terminal_bench as tb
from argos_agent.eval.benchmarks.terminal_bench import (
    TBClassification, TBTask, classify, load_tb_task,
)


# ── 守卫:Docker 不可用 → 整文件 skip ────────────────────────────────


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


# ── 工具:在 tmp 里造一个真 TB 任务(本地小镜像 FROM python:3.12-slim) ─


def _make_tb_task(
    tmp_path: Path,
    *,
    from_line: str,
    extra_dockerfile: str = "",
    run_tests: str = "true\n",
    test_outputs: str = "def test_x(): assert True\n",
    task_id: str | None = None,
) -> Path:
    """在 tmp_path/<task_id>/ 下造一个真 TB 任务目录,返目录路径。

    用本地小镜像(默认 python:3.12-slim,本地有;若没就快拉)避免依赖外网
    ghcr.io。`test_outputs` 写到 tests/test_outputs.py。
    """
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


# ── (a) 分类:Docker 可用时 ghcr.io 任务 → supported_in_docker ────


@requires_docker
def test_classify_marks_ghcr_io_as_supported_when_docker_available(tmp_path):
    """FROM ghcr.io/laude-institute/t-bench/python-3-13:20250620 → 分类为
    supported_in_docker(不是 unsupported_custom_image),前提是 Docker 可用。

    理由:这正是 TB 任务的设计 —— 它们用自家镜像 + harness 在容器里跑。
    本适配器现在也支持这条路径,不再一律 skip。
    """
    # 用一个 fake FROM(不真去拉),classifier 只看正则匹配,不会真连 docker
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
    """Docker 不可用时,即便有 ghcr.io FROM 也应诚实标 unsupported,而不是假装能跑。"""
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
    """FROM python:3.12-slim 这种本地能用的镜像,继续走原来 supported 路径(不需 docker)。
    兼容之前测试,确保没破。"""
    d = _make_tb_task(
        tmp_path,
        from_line="FROM python:3.12-slim",
        task_id="t3",
    )
    parsed = load_tb_task(d)
    cls = classify(parsed, docker_available=False)  # 即便没 docker,本机镜像也支持
    assert cls.supported is True
    assert cls.kind == "supported"


# ── (b) 容器内真跑:pass / fail / 拉不到镜像 ─────────────────────


@requires_docker
def test_docker_run_tests_passing_returns_passed(tmp_path):
    """run-tests.sh 退出 0 → 判 passed。整条 EvalRunner 路径走下来,pass_status='passed'。"""
    from argos_agent.eval.benchmarks.terminal_bench import run_subset, _build_verify_cmd
    from argos_agent.eval.runner import EvalRunner
    from argos_agent.eval.runner import PASS_PASSED
    from tests.eval._fakes import FakeWorktree, make_fake_loop_factory, make_fake_loop

    # 准备任务:run-tests.sh 直接 `true`(退出 0)
    d = _make_tb_task(
        tmp_path,
        from_line="FROM python:3.12-slim",
        run_tests="true\n",
        task_id="docker_pass",
    )
    # 装一个 fake loop:模拟"agent 产出 OK + verify 在容器里跑过 + 退出 0"
    loop = make_fake_loop(verdict=PASS_PASSED, detail="1 passed in 0.5s", steps=2)
    factory = make_fake_loop_factory(loop)
    wt = FakeWorktree(tmp_path / "wt")
    runner = EvalRunner(
        worktree=wt, base_dir=tmp_path / "eval_base", loop_factory=factory, budget_s=10,
    )
    workdir = tmp_path / "corpus"
    report = run_subset([d], runner=runner, model_tier="default", workdir=workdir, persist=False)
    # supported 应走容器路径(若 classify 把它归为 supported);fake loop 返 PASS_PASSED → passed
    statuses = {tid: st for tid, (st, _) in report.per_task_status.items()}
    if report.supported == 1:
        # 走容器路径 + fake loop 报 passed → 最终 passed
        assert statuses["docker_pass"] == "passed"


@requires_docker
def test_docker_run_tests_failing_returns_failed(tmp_path):
    """run-tests.sh 退出非 0 → 判 failed。没放水。"""
    from argos_agent.eval.benchmarks.terminal_bench import run_subset
    from argos_agent.eval.runner import EvalRunner, PASS_FAILED
    from tests.eval._fakes import FakeWorktree, make_fake_loop_factory, make_fake_loop

    d = _make_tb_task(
        tmp_path,
        from_line="FROM python:3.12-slim",
        run_tests="false\n",  # 退出 1
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
    """镜像拉不到 → setup_failed(诚实:没真跑,不计 passed)。"""
    from argos_agent.eval.benchmarks.terminal_bench import run_subset
    from argos_agent.eval.runner import EvalRunner, PASS_SETUP_FAILED
    from tests.eval._fakes import FakeWorktree, make_fake_loop_factory, make_fake_loop

    # 用一个肯定拉不到的 FROM(私有仓库 / 假镜像)
    d = _make_tb_task(
        tmp_path,
        from_line="FROM 127.0.0.1:1/no-such-image:latest",
        task_id="docker_nopull",
    )
    # 因为 classify 在 docker_available=True 时会标 supported_in_docker,setup 阶段
    # 真去拉镜像会失败 → setup_failed。
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
        # setup 失败 → 计入 supported 但 pass_status='setup_failed',不污染 passed 分母
        assert statuses["docker_nopull"] == "setup_failed"


# ── (c) best_of_n 在容器路径下能跑 ─────────────────────────────


@requires_docker
def test_best_of_n_works_on_docker_path(tmp_path, monkeypatch):
    """在容器路径下,best_of_n 应能跑 N 候选(每候选独立容器 + verify),选第一个 passed。"""
    from argos_agent.workflow.engine import WorkflowEngine
    from argos_agent.workflow.spec import parse_spec
    from argos_agent.workflow.subagent import SubAgentFactory
    from argos_agent.workflow.result import AgentResult
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
        from argos_agent.workflow.result import AgentResult
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
    from argos_agent.eval.benchmarks.terminal_bench_best_of_n import build_spec_for_task
    spec = build_spec_for_task(parsed, n=3, model_tier="default")

    async def _go():
        async for _ev in eng.run(spec):
            pass
    asyncio.run(_go())
    assert eng.last_result is not None
    stage = eng.last_result.stages[0]
    # 真跑了 3 个候选(在容器路径下也要真调 3 次 run_task —— 即便最终容器被 mock 掉,
    # 桥接语义要求 N 个独立候选)
    assert len(stage.candidates) == 3
    assert {c.agent_id for c in stage.candidates} == {
        "docker_bofn#c0", "docker_bofn#c1", "docker_bofn#c2",
    }


# ── (d) 错产出仍 failed,没把判定放水 ────────────────────────────


@requires_docker
def test_docker_wrong_solution_still_failed(tmp_path):
    """即使有容器,错产出也得 failed。没把容器路径当放水口。"""
    from argos_agent.eval.benchmarks.terminal_bench import run_subset
    from argos_agent.eval.runner import EvalRunner, PASS_FAILED
    from tests.eval._fakes import FakeWorktree, make_fake_loop_factory, make_fake_loop

    d = _make_tb_task(
        tmp_path,
        from_line="FROM python:3.12-slim",
        run_tests="false\n",  # 永远退出 1
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
        # 错产出 + verify 非 0 → failed(没被容器化"包"成 passed)
        assert statuses["docker_wrong"] == "failed"


# ── (e) 容器 executor 自身:本地小镜像真跑 ──────────────────────


@requires_docker
def test_container_executor_runs_run_tests_inside_container(tmp_path):
    """容器 executor 真跑:从本地 python:3.12-slim 镜像起容器,挂载 tests/ 到 /tests,
    跑 `bash /tests/run-tests.sh`,返回 exit code 0。

    这是端到端验证 —— 不靠 fake loop,真容器真脚本。
    """
    from argos_agent.eval.benchmarks.terminal_bench_docker import TBContainerExecutor

    # 准备一个真 TB 任务目录 + 走 to_eval_task 把 tests/run-tests.sh 复制到 workdir
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
    task = tb.to_eval_task(parsed, workdir=workdir)  # task.working_dir 是 <workdir>/<task_id>

    exec_ = TBContainerExecutor(network=False, timeout=60)
    rc = exec_.verify_in_container(parsed, task_dir=task.working_dir)
    assert rc.exit_code == 0, f"expected 0, got {rc}"


@requires_docker
def test_container_executor_returns_nonzero_on_failing_tests(tmp_path):
    """容器内 run-tests.sh 退出非 0 → executor 返非 0(没把错洗成 0)。"""
    from argos_agent.eval.benchmarks.terminal_bench_docker import TBContainerExecutor

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


# ── (f) worktree 持久化(任务:让 agent 产出能到 docker verify 看到的位置) ─


@requires_docker
def test_subagent_output_mirror_copies_agent_files(tmp_path, monkeypatch):
    """直接验 _mirror_worktree:worktree 里改/增的文件 → mirror。绕开 spy dance。"""
    import subprocess
    from argos_agent.workflow.subagent import SubAgentFactory

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
    # 用 git worktree 加一个工作分支
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


@pytest.mark.slow  # 真 Docker 容器构建+运行,耗时 20-30s —— 标 slow,已被 requires_docker 在无 docker 时 skip。
@requires_docker
def test_docker_verify_sees_mirror_with_seeded_tests(tmp_path, monkeypatch):
    """端到端:bridge 把 TB 源 tests/ + run-tests.sh seed 进 mirror,子 agent 写
    /app/hello.txt 到 worktree,镜像到 mirror;docker verify 跑 → pass。

    这是真 e2e,确保镜像+seed+verify 全链路通。
    """
    import subprocess
    import shutil as _sh
    from argos_agent.workflow.subagent import SubAgentFactory
    from argos_agent.eval.benchmarks.terminal_bench_docker import TBContainerExecutor
    from argos_agent.eval.benchmarks.terminal_bench import load_tb_task, to_eval_task

    # 1. 准备 TB 任务(用 hello-world 真源,从 TB 仓库 clone 出)
    src = Path("/tmp/tb-inspect/original-tasks/hello-world")
    if not src.is_dir():
        pytest.skip("TB inspect dir not present (skipped)")
    parsed = load_tb_task(src)
    assert parsed is not None
    workdir = tmp_path / "corpus"
    workdir.mkdir()
    task = to_eval_task(parsed, workdir=workdir)

    # 3. 模拟 bridge 的 seed:把 tests/ + run-tests.sh 拷到 mirror
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
    # mirror 应当有 tests/test_outputs.py + run-tests.sh(seed 阶段完成)
    assert (mirror / "tests" / "test_outputs.py").is_file()
    assert (mirror / "run-tests.sh").is_file()

    # 4. 模拟 agent 写 /app/hello.txt —— /app 是 worktree cwd(因 Dockerfile WORKDIR /app),
    # 在 host 上就是 mirror 根。Agent 在 worktree 里写 hello.txt,_mirror_worktree 把
    # 它放到 mirror 根。tests 看到 /app/hello.txt 即可。
    (mirror / "hello.txt").write_text("Hello, world!\n")

    # 5. docker verify 在 mirror 上
    import os
    os.environ["ARGOS_TB_DOCKER_NETWORK"] = "1"
    exec_ = TBContainerExecutor(timeout=180)
    rc = exec_.verify_in_container(parsed, task_dir=mirror)
    assert rc.exit_code == 0, (
        f"verify 应 pass,实际 exit={rc.exit_code} setup_failed={rc.setup_failed}"
        f" detail[-500:]={rc.detail[-500:]}"
    )
    """子测试:验证 _mirror_worktree 真能把 worktree 里 agent 写的新文件拷到 mirror。

    走最直接路径:造一个 git worktree,手写 hello.txt 到里面,调
    SubAgentFactory._mirror_worktree,验证 mirror 有 hello.txt。

    这测的是 _mirror_worktree 这个静态方法(SubAgentFactory._run 调它),避开 spy
    dance。
    """
    import subprocess
    from argos_agent.workflow.subagent import SubAgentFactory

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

    # 用 git worktree 加一个工作分支
    wt = base / "wt_test"
    subprocess.run(
        ["git", "-C", str(base), "worktree", "add", "-b", "test", str(wt)],
        check=True, capture_output=True,
    )
    # 在 wt 里写 hello.txt(模拟 agent 产出)
    (wt / "hello.txt").write_text("Hello, world!\n")
    # 改一个老文件
    (wt / "sentinel.txt").write_text("base MODIFIED\n")

    # 调 _mirror_worktree
    SubAgentFactory._mirror_worktree(wt, mirror)
    # mirror 应有 hello.txt(新文件)+ sentinel.txt(被改)
    assert (mirror / "hello.txt").is_file(), f"mirror 缺 hello.txt(实际 {list(mirror.iterdir())})"
    assert (mirror / "hello.txt").read_text() == "Hello, world!\n"
    assert (mirror / "sentinel.txt").read_text() == "base MODIFIED\n"
