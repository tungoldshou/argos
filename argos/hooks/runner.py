from __future__ import annotations

import asyncio
import json
import os
import shlex
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from argos.hooks.config import HookHandler
from argos.hooks.events import HookFired
from argos.hooks.matcher import match
from argos.hooks.payload import render_command


@dataclass(frozen=True, slots=True)
class HookFireResult:
    success: bool
    per_hook: tuple[HookFired, ...]
    stop_reason: str | None = None
    not_found: bool = False
    timed_out: bool = False
    returncode: int | None = None
    stdout: str = ""


async def _run_one(
    handler: HookHandler,
    payload: dict[str, Any],
    *,
    event_name: str,
    cwd: str,
    session_id: str,
) -> HookFired:
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
    from argos.hooks import get_config
    cfg = get_config()
    tool_names = payload.get("tool_names", []) or []
    handlers = match(event_name, tool_names, cfg)
    if not handlers:
        return HookFireResult(success=True, per_hook=(), returncode=None, stdout="")
    cwd_str = str(cwd)
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
            per_hook.append(HookFired(
                event_name=event_name, command="<exception>",
                success=False, returncode=None, elapsed_ms=0,
                error=f"{type(r).__name__}: {r}",
            ))
        else:
            per_hook.append(r)
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
