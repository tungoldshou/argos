"""Internal documentation."""
from __future__ import annotations

from argos.i18n import t

import os
import shlex
import subprocess
from pathlib import Path

from argos import runtime
from argos.tools import ALLOWED_CMDS

from argos.core.types import TRIVIAL_VERIFY_BINS, Verdict  # noqa: F401


def _self_test_enabled() -> bool:
    return os.environ.get("ARGOS_SELF_TEST", "").strip().lower() in ("1", "true", "yes")


def is_trivial_verify(cmd: str) -> bool:
    """Internal documentation."""
    cmd = (cmd or "").strip()
    if not cmd:
        return False
    try:
        bin_name = Path(shlex.split(cmd)[0]).name
    except (ValueError, IndexError):
        return False
    return bin_name in TRIVIAL_VERIFY_BINS


class Verifier:
    """Internal documentation."""

    def __init__(
        self, *, max_rounds: int = 3, inline_timeout: float = 60.0,
        test_generator: "object | None" = None, goal: str | None = None,
    ) -> None:
        self.max_rounds = max_rounds
        self.inline_timeout = inline_timeout
        self._test_generator = test_generator
        self._goal = goal

    def set_goal(self, goal: str) -> None:
        """Update the current run goal (called by loop before each verify phase)."""
        self._goal = goal

    def verify(self, verify_cmd: str | None, *, attempts: int = 1) -> Verdict:
        """Internal documentation."""
        tampered = runtime.detect_tampering()
        if tampered:
            return Verdict.unverifiable(
                detail=t("core2.verify_gate.tampered", files=', '.join(tampered)),
                tampered=tampered, attempts=attempts,
            )

        if not verify_cmd:
            if _self_test_enabled() and self._test_generator is not None:
                verdict = self._try_self_test(attempts=attempts)
                if verdict is not None:
                    return verdict
            return Verdict.no_check(
                detail=t("core2.verify_gate.no_cmd"), attempts=attempts,
            )

        try:
            _bin = Path(shlex.split(verify_cmd)[0]).name
        except (ValueError, IndexError):
            _bin = ""
        if _bin in TRIVIAL_VERIFY_BINS:
            return Verdict.unverifiable(
                detail=t("core2.verify_gate.trivial", cmd=verify_cmd),
                tampered=[], attempts=attempts,
            )

        ok, detail, timed_out = self._run_verify(verify_cmd)
        if timed_out:
            return Verdict.unverifiable(detail=detail, tampered=[], attempts=attempts)
        if ok:
            return Verdict.passed(detail=detail, verify_cmd=verify_cmd, attempts=attempts)
        return Verdict.failed(detail=detail, verify_cmd=verify_cmd, attempts=attempts)

    def _try_self_test(self, *, attempts: int) -> Verdict | None:
        """Internal documentation."""
        from argos.verify.self_test import TestGenerator
        ctx = runtime.current()
        workspace = ctx.workspace
        if workspace is None:
            return None
        gen: TestGenerator = self._test_generator  # type: ignore[assignment]
        proposal = gen.propose_and_validate(
            goal=self._goal or "(no goal provided)", workspace=workspace,
        )
        if proposal is None:
            return None
        ok, detail, timed_out = self._run_verify(proposal.cmd)
        if timed_out:
            return Verdict.unverifiable(
                detail=f"[self_verified timeout] {detail}", tampered=[], attempts=attempts,
            )
        if ok:
            return Verdict.passed_self(
                detail=t("core2.verify_gate.self_verified_weak", detail=detail),
                verify_cmd=proposal.cmd, attempts=attempts,
            )
        return Verdict.failed(
            detail=t("core2.verify_gate.self_verified_failed", detail=detail),
            verify_cmd=proposal.cmd, attempts=attempts,
        )

    def _run_verify(self, cmd: str) -> tuple[bool, str, bool]:
        """Internal documentation."""
        try:
            parts = shlex.split(cmd)
        except ValueError as e:
            return False, t("core2.verify_gate.parse_failed", error=e), False

        if not parts or Path(parts[0]).name not in ALLOWED_CMDS:
            return False, t("core2.verify_gate.not_allowlisted", cmd=cmd), False

        ctx = runtime.current()
        verify_dir, workspace = ctx.verify_dir, ctx.workspace
        verify_dir.mkdir(parents=True, exist_ok=True)
        workspace.mkdir(parents=True, exist_ok=True)

        env = dict(os.environ)
        env["PYTHONPATH"] = str(workspace) + os.pathsep + env.get("PYTHONPATH", "")
        env["PYTHONDONTWRITEBYTECODE"] = "1"

        try:
            r = subprocess.run(
                parts, cwd=verify_dir, capture_output=True, text=True,
                timeout=self.inline_timeout, env=env,
            )
        except subprocess.TimeoutExpired:
            return False, t("core2.verify_gate.timeout", cmd=cmd, timeout=self.inline_timeout), True
        except Exception as e:  # noqa: BLE001
            return False, t("core2.verify_gate.exec_failed", error=e), False

        out = (r.stdout or "")[-1500:]
        err = (r.stderr or "")[-1500:]
        detail = f"[exit_code={r.returncode}]\n{out}\n{err}".strip()
        return r.returncode == 0, detail, False
