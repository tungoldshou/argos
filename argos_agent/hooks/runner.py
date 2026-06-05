"""子进程 runner:asyncio.create_subprocess_exec 跑 hook,JSON stdio,超时 / 模板 / env。

(spec §2.3 / §3 错误处理 / §4.3 子进程集成)
- 不用 Seatbelt(spec D2:hook 是用户代码,与 agent 同权限)
- 同一事件多 hook → asyncio.gather 并行,PreToolUse 任一 fail → 整体 success=False
- 超时:asyncio.wait_for → SIGTERM → 2s 后 SIGKILL
- stdout:非 JSON 忽略;合法 JSON 取 stopReason 字段
- stdin:写 JSON payload(close 让 hook 收 EOF)
- env:继承 host + 注 ARGOS_HOOK_EVENT
- cwd:loop 传 _workspace
"""
from __future__ import annotations

import asyncio
import json
import os
import shlex
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from argos_agent.hooks.config import HookHandler
from argos_agent.hooks.events import HookFired
from argos_agent.hooks.matcher import match
from argos_agent.hooks.payload import render_command


@dataclass(frozen=True, slots=True)
class HookFireResult:
    """一次 fire 的聚合结果(给 loop 用)。

    `returncode` / `stdout` 是单 hook 时的便捷聚合(多 hook 时取首个);详尽
    信息看 `per_hook`。
    """
    success: bool                     # True=全部 ok / Pre 之外非 0 不算 fail
    per_hook: tuple[HookFired, ...]   # 各 hook 详情(给活动栏)
    stop_reason: str | None = None    # PreToolUse 反喂用(spec §2.5)
    not_found: bool = False
    timed_out: bool = False
    returncode: int | None = None     # 聚合:首个 hook 的 returncode(便于单 hook 场景)
    stdout: str = ""                  # 聚合:首个 hook 的 stdout


async def _run_one(
    handler: HookHandler,
    payload: dict[str, Any],
    *,
    event_name: str,
    cwd: str,
    session_id: str,
) -> HookFired:
    """跑一个 hook 子进程;返回 HookFired 事件(给活动栏 + loop 用)。"""
    # 模板替换
    try:
        cmd_str = render_command(
            handler.command,
            cwd=cwd,
            session_id=session_id,
            tool_names=payload.get("tool_names", []),
        )
    except Exception as e:  # noqa: BLE001
        return HookFired(
            event_name=event_name, command=handler.command,
            success=False, returncode=None, elapsed_ms=0,
            error=f"render failed: {e}",
        )
    # shlex.split → argv 列表(避免 shell injection;用户脚本走 stdin 拿 payload)
    try:
        argv = shlex.split(cmd_str)
    except ValueError as e:
        return HookFired(
            event_name=event_name, command=cmd_str,
            success=False, returncode=None, elapsed_ms=0,
            error=f"shlex failed: {e}",
        )
    if not argv:
        return HookFired(
            event_name=event_name, command=cmd_str,
            success=False, returncode=None, elapsed_ms=0,
            error="empty command",
        )
    # env 继承 + 注入 ARGOS_HOOK_EVENT
    env = dict(os.environ)
    env["ARGOS_HOOK_EVENT"] = event_name
    # stdin payload
    stdin_data = json.dumps(payload, ensure_ascii=False)
    t0 = time.time()
    try:
        proc = await asyncio.create_subprocess_exec(
            *argv,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=cwd,
            env=env,
        )
    except FileNotFoundError as e:
        return HookFired(
            event_name=event_name, command=cmd_str,
            success=False, returncode=None,
            elapsed_ms=int((time.time() - t0) * 1000),
            not_found=True, error=f"file not found: {e}",
        )
    except OSError as e:
        return HookFired(
            event_name=event_name, command=cmd_str,
            success=False, returncode=None,
            elapsed_ms=int((time.time() - t0) * 1000),
            error=f"OS error: {e}",
        )
    timeout_s = handler.timeout / 1000.0
    try:
        stdout_b, stderr_b = await asyncio.wait_for(
            proc.communicate(input=stdin_data.encode("utf-8")),
            timeout=timeout_s,
        )
        elapsed_ms = int((time.time() - t0) * 1000)
        returncode = proc.returncode
    except asyncio.TimeoutError:
        # 杀进程:SIGTERM → 2s 后 SIGKILL
        try:
            proc.terminate()
        except ProcessLookupError:
            pass
        try:
            await asyncio.wait_for(proc.wait(), timeout=2.0)
        except asyncio.TimeoutError:
            try:
                proc.kill()
            except ProcessLookupError:
                pass
            await proc.wait()
        elapsed_ms = int((time.time() - t0) * 1000)
        return HookFired(
            event_name=event_name, command=cmd_str,
            success=False, returncode=None,
            elapsed_ms=elapsed_ms, timed_out=True,
            error=f"timeout after {handler.timeout}ms",
        )
    stdout = stdout_b.decode("utf-8", errors="replace")
    stderr = stderr_b.decode("utf-8", errors="replace")
    # 解析 stdout JSON(若合法);取 stopReason
    stop_reason: str | None = None
    stripped = stdout.strip()
    if stripped.startswith("{"):
        try:
            obj = json.loads(stripped)
            if isinstance(obj, dict):
                sr = obj.get("stopReason")
                if isinstance(sr, str):
                    stop_reason = sr
        except json.JSONDecodeError:
            pass
    success = returncode == 0
    return HookFired(
        event_name=event_name, command=cmd_str,
        success=success, returncode=returncode,
        elapsed_ms=elapsed_ms,
        stop_reason=stop_reason,
        error=stderr.strip() or None,
        stdout=stdout,
    )


async def fire(
    event_name: str,
    payload: dict[str, Any],
    *,
    cwd: str | Path,
    session_id: str,
) -> HookFireResult:
    """触发 event_name 对应的所有 hook(并行);返回聚合结果。

    Args:
        event_name: PreToolUse / PostToolUse / Stop / UserPromptSubmit / SessionStart
        payload: build_*_payload 构造的 dict(写到 hook stdin)
        cwd: hook 进程的 CWD(= loop._workspace)
        session_id: 用于 {session_id} 模板替换

    Returns:
        HookFireResult,含 per_hook 详情 + success(全部成功=True;Pre 时任一 fail=False)
    """
    from argos_agent.hooks import get_config   # 避免循环 import
    cfg = get_config()
    tool_names = payload.get("tool_names", []) or []
    handlers = match(event_name, tool_names, cfg)
    if not handlers:
        return HookFireResult(success=True, per_hook=(), returncode=None, stdout="")
    cwd_str = str(cwd)
    # 并行跑;return_exceptions=True 防一个 hook 抛异常卡住其他
    results = await asyncio.gather(
        *(
            _run_one(h, payload, event_name=event_name, cwd=cwd_str, session_id=session_id)
            for h in handlers
        ),
        return_exceptions=True,
    )
    per_hook: list[HookFired] = []
    for r in results:
        if isinstance(r, BaseException):
            # 一个 hook 抛了:把它当 fail 收(其他不受影响)
            per_hook.append(HookFired(
                event_name=event_name, command="<exception>",
                success=False, returncode=None, elapsed_ms=0,
                error=f"{type(r).__name__}: {r}",
            ))
        else:
            per_hook.append(r)
    # 聚合:任一 fail → success=False(给 PreToolUse 阻塞判)
    success = all(h.success for h in per_hook)
    stop_reason: str | None = None
    not_found = any(h.not_found for h in per_hook)
    timed_out = any(h.timed_out for h in per_hook)
    for h in per_hook:
        if h.stop_reason and not stop_reason:
            stop_reason = h.stop_reason
    return HookFireResult(
        success=success, per_hook=tuple(per_hook),
        stop_reason=stop_reason, not_found=not_found, timed_out=timed_out,
        returncode=per_hook[0].returncode if per_hook else None,
        stdout=per_hook[0].stdout if per_hook else "",
    )
