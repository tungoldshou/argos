from __future__ import annotations

import asyncio
import concurrent.futures
import os
import re
import shlex
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Callable, Iterable

from argos import runtime
from argos.i18n import t
from argos.tools import ALLOWED_CMDS

if TYPE_CHECKING:
    from argos.core.models import ModelClient


@dataclass(frozen=True, slots=True)
class TestProposal:

    __test__ = False

    cmd: str
    content: str
    test_path: str
    canary_passed: bool
    reason: str = ""


TestProposer = Callable[[str, Path], tuple[str, str, str] | None]


def default_test_proposer(goal: str, workspace: Path) -> tuple[str, str, str] | None:
    return None



_REVIEWER_SYSTEM = """\
You are an INDEPENDENT REVIEWER. Your ONLY job is to write a pytest-style test \
for a task that a coder agent just attempted. You are NOT the coder — you must \
not look at the coder's implementation. You only know the GOAL and the files \
present in the workspace.

Rules (strictly enforced by a canary guard after you respond):
1. The test MUST FAIL on an EMPTY workspace (no files) — it must genuinely \
   depend on something the coder was supposed to produce.
2. The test MUST use only commands in this whitelist: python3, pytest, diff, cat, grep, \
   head, tail, wc, ls, find, echo, true, false, touch, mkdir, cp, mv, rm, sed, awk, sort, \
   uniq, xargs, test, uname, date, pwd, env, printenv.
3. Respond with EXACTLY this structure and nothing else:

CMD: <single shell command to run the test, e.g. "python3 _reviewer_test.py">
TESTFILE: _reviewer_test.py
CONTENT:
```python
<test code here>
```

Do not add explanations outside this structure."""


def reviewer_llm_proposer(model_client: "ModelClient") -> TestProposer:
    """Return a TestProposer that calls model_client under a distinct reviewer-role system prompt.

    Maker/checker separation: the reviewer prompt instructs the model to act as an
    independent inspector, NOT as the coder. The same model weights are used but the
    role is explicitly different — the coder's implementation context is excluded from
    the prompt, and the reviewer is told it must not assume the coder's code is correct.

    The async model call is dispatched to a fresh thread (new event loop) so that this
    sync proposer can be called from either a sync or async context without nesting loops.
    """
    def _proposer(goal: str, workspace: Path) -> tuple[str, str, str] | None:
        # Collect workspace file listing (names only, no content — reviewer must not see impl).
        try:
            file_list = "\n".join(
                str(p.relative_to(workspace))
                for p in sorted(workspace.rglob("*"))
                if p.is_file() and not p.name.startswith(".")
            )
        except Exception:  # noqa: BLE001
            file_list = "(unable to list)"

        user_msg = (
            f"TASK GOAL: {goal}\n\n"
            f"FILES IN WORKSPACE (names only — do not assume their contents are correct):\n"
            f"{file_list or '(empty workspace)'}\n\n"
            "Write a test following the rules in your system prompt."
        )

        async def _call() -> str:
            return await model_client.complete(
                [{"role": "user", "content": user_msg}],
                system=_REVIEWER_SYSTEM,
            )

        # Run async call in an isolated thread with its own event loop so this
        # sync proposer works whether or not there is a running loop on the caller's thread.
        # ponytail: one-thread executor avoids nest_asyncio dependency
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            fut = pool.submit(asyncio.run, _call())
            try:
                response = fut.result(timeout=60.0)
            except Exception:  # noqa: BLE001 — model error → stay unverifiable
                return None

        return _parse_reviewer_response(response)

    return _proposer


def _parse_reviewer_response(response: str) -> tuple[str, str, str] | None:
    """Parse the structured reviewer response into (cmd, content, test_path).

    Returns None if the response is malformed or empty — stays unverifiable.
    """
    # Extract CMD line
    cmd_m = re.search(r"^CMD:\s*(.+)$", response, re.MULTILINE)
    if not cmd_m:
        return None
    cmd = cmd_m.group(1).strip().strip('"').strip("'")

    # Extract TESTFILE line
    tf_m = re.search(r"^TESTFILE:\s*(.+)$", response, re.MULTILINE)
    test_path = tf_m.group(1).strip() if tf_m else "_reviewer_test.py"

    # Extract ```python ... ``` block
    code_m = re.search(r"```python\s*\n(.*?)```", response, re.DOTALL)
    if not code_m:
        return None
    content = code_m.group(1)

    if not cmd or not content.strip():
        return None
    return cmd, content, test_path




def _is_whitelisted(cmd: str) -> bool:
    try:
        parts = shlex.split(cmd)
    except ValueError:
        return False
    if not parts:
        return False
    return Path(parts[0]).name in ALLOWED_CMDS


def _run_in_workspace(cmd: str, workspace: Path, *, timeout: float = 30.0) -> tuple[int, str, str]:
    try:
        parts = shlex.split(cmd)
    except ValueError as e:
        return 127, "", f"shlex failed: {e}"
    if not parts or Path(parts[0]).name not in ALLOWED_CMDS:
        return 127, "", f"cmd not whitelisted: {cmd}"
    env = dict(os.environ)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    try:
        r = subprocess.run(
            parts, cwd=str(workspace), capture_output=True, text=True,
            timeout=timeout, env=env,
        )
        return r.returncode, r.stdout or "", r.stderr or ""
    except subprocess.TimeoutExpired:
        return -1, "", "timeout"
    except Exception as e:  # noqa: BLE001
        return 127, "", f"subprocess error: {e}"


def _canary_check(cmd: str, workspace: Path, *, timeout: float = 30.0) -> tuple[bool, str]:
    if not workspace.is_dir():
        return False, t("verify.self_test.workspace_missing", workspace=workspace)
    backup = workspace.parent / f".{workspace.name}.canary_backup"
    if backup.exists():
        shutil.rmtree(backup, ignore_errors=True)
    rc: int = -1
    try:
        workspace.rename(backup)
        workspace.mkdir(parents=True, exist_ok=True)
        rc, _out, _err = _run_in_workspace(cmd, workspace, timeout=timeout)
    finally:
        if workspace.exists():
            shutil.rmtree(workspace, ignore_errors=True)
        if backup.exists():
            backup.rename(workspace)
    if rc == 0:
        return False, t("verify.self_test.canary_failed", cmd=cmd)
    return True, ""


def _restore_check(cmd: str, workspace: Path, *, timeout: float = 30.0) -> bool:
    rc, _out, _err = _run_in_workspace(cmd, workspace, timeout=timeout)
    return rc != -1




@dataclass(frozen=True, slots=True)
class TestGenerator:

    __test__ = False

    proposer: TestProposer | None = None
    timeout_s: float = 30.0
    canary_enabled: bool = True

    def propose_and_validate(
        self, *, goal: str, workspace: Path,
    ) -> TestProposal | None:
        if self.proposer is None:
            return None
        if not workspace.exists():
            return None

        # 1) propose
        proposed = self.proposer(goal, workspace)
        if proposed is None:
            return None
        cmd, content, test_path = proposed
        if not cmd or not content or not test_path:
            return None

        if not _is_whitelisted(cmd):
            return None

        tampered = runtime.detect_tampering()
        if tampered:
            return None

        from argos import runtime as _rt
        ctx = _rt.current()
        verify_dir = ctx.verify_dir
        test_abs = Path(test_path)
        if not test_abs.is_absolute():
            test_abs = verify_dir / test_abs
        try:
            test_abs.parent.mkdir(parents=True, exist_ok=True)
            test_abs.write_text(content, encoding="utf-8")
        except OSError:
            return None

        if self.canary_enabled:
            passed, reason = _canary_check(cmd, workspace, timeout=self.timeout_s)
            if not passed:
                try:
                    if test_abs.exists():
                        test_abs.unlink()
                except OSError:
                    pass
                return None
        else:
            reason = ""

        if not _restore_check(cmd, workspace, timeout=self.timeout_s):
            try:
                if test_abs.exists():
                    test_abs.unlink()
            except OSError:
                pass
            return None

        return TestProposal(
            cmd=cmd, content=content, test_path=str(test_abs),
            canary_passed=True, reason=reason,
        )
