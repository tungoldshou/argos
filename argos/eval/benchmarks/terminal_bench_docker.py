"""Internal documentation."""
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

_DEFAULT_VERIFY_TIMEOUT = 600.0


@dataclass(frozen=True, slots=True)
class ContainerVerifyResult:
    """Internal documentation."""
    exit_code: int
    detail: str
    timed_out: bool = False
    setup_failed: bool = False


class TBContainerExecutor:
    """Internal documentation."""

    def __init__(self, *, network: bool | None = None, timeout: float = _DEFAULT_VERIFY_TIMEOUT):
        if network is None:
            network = os.environ.get("ARGOS_TB_DOCKER_NETWORK") == "1"
        self._network = network
        self._timeout = timeout
        if shutil.which("docker") is None:
            raise RuntimeError(t("eval.docker.no_docker"))

    def image_ready(self, tb_task: TBTask) -> tuple[bool, str]:
        """Internal documentation."""
        if not tb_task.dockerfile_lines:
            return False, ""
        from_line = tb_task.dockerfile_lines[0].strip()
        # "FROM ghcr.io/laude-institute/t-bench/python-3-13:20250620"
        parts = from_line.split()
        if len(parts) < 2 or parts[0].upper() != "FROM":
            return False, ""
        base_ref = parts[1]
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
        """Internal documentation."""
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
        """Internal documentation."""
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
        run_tests_src = tb_task.source_dir / "run-tests.sh"
        if not run_tests_src.is_file():
            return ContainerVerifyResult(
                exit_code=-1, detail=f"setup_failed: {run_tests_src} not found",
                setup_failed=True,
            )
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
        out = (r.stdout or "")[-1500:]
        err = (r.stderr or "")[-1500:]
        detail = f"[exit_code={r.returncode}]\n{out}\n{err}".strip()
        return ContainerVerifyResult(
            exit_code=r.returncode, detail=detail,
        )
