"""Terminal-Bench 容器执行器(Docker 路径)。

动机:真 TB 任务几乎都用 `FROM ghcr.io/laude-institute/t-bench/...` 自家镜像,
本机没这镜像 → 之前 classify 一律标 unsupported_custom_image → 真 TB 任务全被
skip。本模块让"有 Docker + 镜像可拉"的任务在容器里真跑(setup / 跑 agent /
跑 run-tests.sh),沿用 EvalRunner 的三态 Verifier 语义,不动 ALLOWED_CMDS / 三态
判定 / 篡改检测。

架构:
  TBContainerExecutor = 薄包装 docker CLI(避免引 docker SDK 多余依赖):
    · start_container(image, workdir, env) → 持久容器,sleep infinity,挂
      workdir 到 /app
    · exec_in_container(cid, cmd) → 容器内跑命令,返 (rc, stdout, stderr)
    · verify_in_container(tb_task, workdir) → 在容器内跑官方 run-tests.sh,
      返 rc(0 = passed, 非 0 = failed, 异常 = setup_failed)
    · stop_container(cid) → 收尾

安全(任务硬规则):
  · --network=none 默认。任务若真需网络,pull 阶段失败 / 装包失败如实标 setup_failed。
  · 只挂任务 workdir 到 /app(读 + 写),其他路径不挂。
  · 容器跑完即删(--rm)。
  · 退出码是 ground truth:0 = pass,非 0 = fail,超时 = unverifiable(由 EvalRunner
    走三态)。

为什么不用 docker SDK:少一个依赖,Argos 是 TUI + sandbox 边的应用,docker CLI
sp + JSON 解析足够。SDK 在多平台二进制分发有摩擦。

Honest skip(模块级 hard rule):
  · docker 不在 PATH → 启动即 fail-closed,run_subset 在调用前就 classify 判 unsupported
  · 镜像拉不到 / build 失败 → 返 (rc=-1, detail="pull_failed:...") → EvalRunner
    标 setup_failed,不计入 passed 分母
  · run-tests.sh 超时 → 返 (-1, "timeout") → setup_failed(同上)
"""
from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import tempfile
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from argos.eval.benchmarks.terminal_bench import TBTask
from argos.i18n import t

log = logging.getLogger(__name__)

# 默认超时:TB 任务 max_test_timeout_sec 200s + 容器首跑要 apt install + uv pip install
# (实测 csv-to-parquet 装 pytest+pandas+pyarrow ≈ 280s),给 600s 安全边界。
# 修(2026-06-09):之前 240s 太临界,真 TB 任务首次 apt/uv 装包就超时 → setup_failed →
# bridge 当成 failed(其实是 setup 问题不是测试问题),数据失真。
_DEFAULT_VERIFY_TIMEOUT = 600.0


@dataclass(frozen=True, slots=True)
class ContainerVerifyResult:
    """容器内 verify 跑完的结果。"""
    exit_code: int          # 0 = passed;非 0 = failed;-1 = setup/timeout 失败
    detail: str             # stdout+stderr 末 1500 字符(同 verify_gate 风格)
    timed_out: bool = False
    setup_failed: bool = False  # 真出错(docker 跑不起来 / 镜像拉不到)


class TBContainerExecutor:
    """真容器执行器:跑 TB 任务的 setup + verify。

    network:True/False/None。
      True → 容器开网络(让 curl/uv/pip 能跑;TB 任务几乎都需联网装包)
      False → 严格无网络(防 agent 越权外联;漏在 setup_failed)
      None → 默认无网络,设环境变量 ARGOS_TB_DOCKER_NETWORK=1 可放开

    timeout:容器内 run-tests.sh 跑的超时(秒)。
    """

    def __init__(self, *, network: bool | None = None, timeout: float = _DEFAULT_VERIFY_TIMEOUT):
        if network is None:
            network = os.environ.get("ARGOS_TB_DOCKER_NETWORK") == "1"
        self._network = network
        self._timeout = timeout
        if shutil.which("docker") is None:
            raise RuntimeError(t("eval.docker.no_docker"))

    def image_ready(self, tb_task: TBTask) -> tuple[bool, str]:
        """检查镜像是否已在本机:有 → 返 (True, name);无 → 返 (False, base_ref)。

        判定逻辑:优先用任务 Dockerfile 的第一行(FROM ...)直接拉;若任务有额外
        COPY / RUN,得 build。先看 FROM 对应的 base 是否在 docker images 里,没就
        pull。**不真 build**(那是 v1 之外的事:copy 任务文件、docker build)——
        大多数 TB 任务的 Dockerfile 就是 `FROM <base>` + `WORKDIR /app`,直接用
        base 即可。
        """
        if not tb_task.dockerfile_lines:
            return False, ""
        from_line = tb_task.dockerfile_lines[0].strip()
        # "FROM ghcr.io/laude-institute/t-bench/python-3-13:20250620"
        parts = from_line.split()
        if len(parts) < 2 or parts[0].upper() != "FROM":
            return False, ""
        base_ref = parts[1]
        # 本机有?
        try:
            r = subprocess.run(
                ["docker", "image", "inspect", base_ref, "--format", "{{.Id}}"],
                capture_output=True, text=True, timeout=10,
            )
            if r.returncode == 0 and r.stdout.strip():
                return True, base_ref
        except subprocess.TimeoutExpired:
            pass
        return False, base_ref

    def pull_image(self, base_ref: str) -> tuple[bool, str]:
        """docker pull base_ref。成功 → (True, '');失败 → (False, stderr 末 800 字符)。"""
        try:
            r = subprocess.run(
                ["docker", "pull", base_ref],
                capture_output=True, text=True, timeout=300,
            )
            if r.returncode == 0:
                return True, ""
            return False, (r.stderr or r.stdout or "")[-800:]
        except subprocess.TimeoutExpired:
            return False, "pull_timeout (>300s)"
        except Exception as e:  # noqa: BLE001
            return False, f"{type(e).__name__}: {e}"

    def verify_in_container(
        self,
        tb_task: TBTask,
        *,
        task_dir: Path,
    ) -> ContainerVerifyResult:
        """在容器内跑 TB 任务的 run-tests.sh,返退出码 + 详情。

        task_dir 是 to_eval_task 落盘后的任务目录(包含 task.yaml / tests/ / verify_cmd
        / Dockerfile / goal.md 等)。run-tests.sh 没被 to_eval_task 落盘到 task_dir;
        从 tb_task.source_dir / "run-tests.sh" 拿原文。
        """
        task_dir = Path(task_dir)
        if not task_dir.is_dir():
            return ContainerVerifyResult(
                exit_code=-1, detail=f"setup_failed: task_dir {task_dir} not found",
                setup_failed=True,
            )
        if not (task_dir / "tests" / "test_outputs.py").is_file():
            return ContainerVerifyResult(
                exit_code=-1, detail="setup_failed: tests/test_outputs.py not in task_dir",
                setup_failed=True,
            )
        # run-tests.sh 没被 to_eval_task 落盘(它走 verify_cmd 那条路径);从源任务目录读
        run_tests_src = tb_task.source_dir / "run-tests.sh"
        if not run_tests_src.is_file():
            return ContainerVerifyResult(
                exit_code=-1, detail=f"setup_failed: {run_tests_src} not found",
                setup_failed=True,
            )
        # 1. 拿 base_ref
        ready, base_ref = self.image_ready(tb_task)
        if not ready:
            ok, err = self.pull_image(base_ref)
            if not ok:
                return ContainerVerifyResult(
                    exit_code=-1, detail=f"setup_failed: docker pull {base_ref} failed: {err}",
                    setup_failed=True,
                )
        # 2. docker run
        network_flag = [] if self._network else ["--network=none"]
        if self._network:
            log.info("[docker] running %s with network=ENABLED (TB tasks typically need internet for pip/uv)", base_ref)
        # TEST_DIR=/tests;task_dir 挂到 /app(让 agent 写文件);task_dir/tests 单独挂 /tests
        # (覆盖路径,这样 /tests/test_outputs.py 对得上;run-tests.sh 内容里通常只调
        # pytest $TEST_DIR/test_outputs.py,不调自身路径)
        import shutil as _sh
        target_run_tests = task_dir / "tests" / "run-tests.sh"
        _sh.copy(run_tests_src, target_run_tests)
        try:
            target_run_tests.chmod(0o755)
        except OSError:
            pass
        cmd = [
            "docker", "run", "--rm",
            *network_flag,
            "-v", f"{task_dir}:/app",
            "-v", f"{task_dir / 'tests'}:/tests",
            "-e", "TEST_DIR=/tests",
            "-e", "PYTHONDONTWRITEBYTECODE=1",
            base_ref,
            "bash", "/tests/run-tests.sh",
        ]
        try:
            r = subprocess.run(
                cmd, capture_output=True, text=True,
                timeout=self._timeout, env={**os.environ},
            )
        except subprocess.TimeoutExpired:
            return ContainerVerifyResult(
                exit_code=-1,
                detail=t("eval.docker.timeout", timeout=self._timeout),
                timed_out=True, setup_failed=True,
            )
        except Exception as e:  # noqa: BLE001
            return ContainerVerifyResult(
                exit_code=-1, detail=t("eval.docker.run_failed", exc_type=type(e).__name__, exc=e),
                setup_failed=True,
            )
        # detail 风格同 verify_gate:[exit_code=N]\nstdout\nstderr
        out = (r.stdout or "")[-1500:]
        err = (r.stderr or "")[-1500:]
        detail = f"[exit_code={r.returncode}]\n{out}\n{err}".strip()
        return ContainerVerifyResult(
            exit_code=r.returncode, detail=detail,
        )
