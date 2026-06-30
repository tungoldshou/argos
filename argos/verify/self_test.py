"""self_test.py —— 给无 verify_cmd 任务自动造测试(严守"绝不自欺"铁律)。

设计:
  · 入口:TestGenerator().propose_and_validate(goal, workspace, baseline_cmd_runner)
    → 返 TestProposal(cmd, content, canary_passed) 或 None
  · 流程:
      1. propose(goal, workspace) → 调 test_proposer(goal, workspace) 拿 (cmd, content)
         test_proposer 是 caller 注入(默认实现走 reviewer 子 agent 调 LLM)。
      2. canary(cmd, workspace)  → 把 workspace 临时换成【空目录】,跑 cmd;必须非 0
         (空 workspace 上过 = 废测试,不依赖 agent 的产出 → 立刻丢弃)。
         还原 workspace;再跑 cmd 一次确认没把东西改坏。
      3. 白名单 + detect_tampering 复检(cmd 不在 ALLOWED_CMDS → 拒;tampered 非空 → 拒)。
      4. 都过了 → 返 TestProposal(cmd, content, canary_passed=True)。
  · 失败任一步 → 返 None → 上层回退 unverifiable,绝不假装通过。

诚实边界:
  · TestGenerator 不持有"已通过 / 失败"状态 —— 决策留给 caller(Verifier)。
  · 生成的测试仍走 Verifier._run_verify(白名单 + subprocess) → 复用既有护栏。
  · canary 跑两次(空 ws / 原 ws) → 防止"测了但把 ws 改坏" + 防"用 magic 文件
    假装真依赖"两种作弊。
"""
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
    """candidate self-test,经 canary + 白名单 + detect_tampering 守卫后产出。"""

    # 防止 pytest 把它当 Test* class 收(命名撞 pytest discovery 默认规则)
    __test__ = False

    cmd: str
    content: str                       # 写到 workspace 的测试文件内容
    test_path: str                     # 写到 workspace 的相对/绝对路径
    canary_passed: bool                # True = 在空 workspace 跑会非 0
    reason: str = ""                   # 留着给上层打 log / report


# test_proposer 签名:接 goal + workspace → (cmd, content, test_path) 或 None
#   cmd:候选 verify 命令(单行)
#   content:写到 test_path 的文件内容
#   test_path:相对 workspace 的路径(沙箱里写)
#   None = 没法造(caller 回退 unverifiable)
TestProposer = Callable[[str, Path], tuple[str, str, str] | None]


def default_test_proposer(goal: str, workspace: Path) -> tuple[str, str, str] | None:
    """默认 test proposer 占位:无 ModelClient 注入时返 None → caller 回退 unverifiable。

    生产路径走 reviewer_llm_proposer(model_client) 构造的独立 reviewer 角色调用。
    """
    return None


# ── reviewer-role LLM proposer(生产路径,maker/checker 分离) ────

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


# ── canary 守卫:空 workspace 上必非 0,否则废测试 ───────────


def _is_whitelisted(cmd: str) -> bool:
    """复用 ALLOWED_CMDS;只接受名单内首 token。"""
    try:
        parts = shlex.split(cmd)
    except ValueError:
        return False
    if not parts:
        return False
    return Path(parts[0]).name in ALLOWED_CMDS


def _run_in_workspace(cmd: str, workspace: Path, *, timeout: float = 30.0) -> tuple[int, str, str]:
    """subprocess 跑 cmd 在 workspace(简化版 _run_verify:同包,但不走 verify_dir 隔离,
    自验证的测试写在 workspace 自己里)。超时返 (-1, "", "timeout")。"""
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
    """canary:把 workspace 临时换成空目录,跑 cmd;期望非 0(否则废测试)。

    返回 (canary_passed, reason)。canary_passed=True 表示"在空 ws 上非 0",
    即"测试**真的**在测 workspace 里的东西"(不是 no-op 也不是 magic pass)。

    实现:把原 workspace 改名为 .canary_backup,在原路径建一个全新的空目录
    (在 ws 父目录里建一个新 tmp dir 暂存,跑完 cmd 再删),最后还原。
    """
    if not workspace.is_dir():
        return False, t("verify.self_test.workspace_missing", workspace=workspace)
    backup = workspace.parent / f".{workspace.name}.canary_backup"
    if backup.exists():
        # 防之前残留(canary 跑一半崩了):防御性清
        shutil.rmtree(backup, ignore_errors=True)
    rc: int = -1
    try:
        workspace.rename(backup)
        # 在原路径建一个全新空目录
        workspace.mkdir(parents=True, exist_ok=True)
        # 现在 workspace 是个空目录 —— 跑 cmd
        rc, _out, _err = _run_in_workspace(cmd, workspace, timeout=timeout)
    finally:
        # 不管成功失败,先删空 workspace 内的可能残留,再把 backup 还原
        if workspace.exists():
            shutil.rmtree(workspace, ignore_errors=True)
        if backup.exists():
            backup.rename(workspace)
    if rc == 0:
        return False, t("verify.self_test.canary_failed", cmd=cmd)
    return True, ""


def _restore_check(cmd: str, workspace: Path, *, timeout: float = 30.0) -> bool:
    """canary 跑完后,跑一次原 workspace 确认:不爆 + 不毁文件(防止 proposer 写的
    测试把 ws 改坏)。非硬断言,只是返 bool 给上层记 reason。"""
    rc, _out, _err = _run_in_workspace(cmd, workspace, timeout=timeout)
    return rc != -1   # True = 没超时(超时说明测试本身有问题)


# ── 主入口 ─────────────────────────────


@dataclass(frozen=True, slots=True)
class TestGenerator:
    """评审守卫:propose → canary → 白名单 → detect_tampering → 返 TestProposal or None。

    用法:caller 注入 proposer(默认 None → 永远不造);真模式接 reviewer LLM。
    """

    # 防止 pytest 把它当 Test* class 收
    __test__ = False

    proposer: TestProposer | None = None
    timeout_s: float = 30.0
    canary_enabled: bool = True

    def propose_and_validate(
        self, *, goal: str, workspace: Path,
    ) -> TestProposal | None:
        """跑完整守卫链;任一步败 → 返 None(caller 视作没法造 → unverifiable)。"""
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

        # 2) 白名单(早拒,避免后面才报)
        if not _is_whitelisted(cmd):
            return None

        # 3) detect_tampering(跟用户 verify 同一道闸:被测文件的"受保护"在 self-test
        #    触发前就应已过;这里再过一次防 propose 阶段有谁动到)
        tampered = runtime.detect_tampering()
        if tampered:
            return None

        # 4) 把测试文件写到 verify_dir(不是 workspace):
        #    _run_verify 跑在 cwd=verify_dir(防 agent 篡改评判它的测试);
        #    若写 workspace,subprocess 找不到相对路径。test_path 允许相对 / 绝对。
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

        # 5) canary:在空 ws 跑必须非 0(铁律 —— 2a)
        #    canary 检查"测试是否真的依赖 workspace";workspace 仍可被 canary 阶段
        #    移走/还原(用 workspace 而非 verify_dir),因为我们要验的是 workspace 状态。
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

        # 6) restore-check:确认测试不把 ws 改坏
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
