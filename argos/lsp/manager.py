"""Internal documentation."""
from __future__ import annotations

import asyncio
import concurrent.futures
import logging
import os
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Awaitable, Callable, Mapping
from urllib.parse import quote

from argos.lsp.client import LspClient, LspProtocolError, LspStreamClosed, encode_frame
from argos.lsp.config import LspConfig, LspServerConfig
from argos.lsp.events import LspDiagnosticEvent, LspServerEvent

log = logging.getLogger(__name__)



class ServerStatus(str, Enum):
    NOT_STARTED = "NotStarted"
    STARTING = "Starting"
    INITIALIZING = "Initializing"
    INITIALIZED = "Initialized"
    READY = "Ready"
    CRASHED = "Crashed"
    DISABLED = "Disabled"
    SHUTDOWN = "Shutdown"


_BACKOFF_SECONDS: float = 30.0

_REQUEST_TIMEOUT_S: float = 5.0

_SLOW_STREAK_LIMIT_MS: int = 30_000


_LARGE_FILE_BYTES: int = 1_048_576   # 1 MiB

_CONTENT_CACHE: dict[str, str] = {}


@dataclass
class _Server:
    """Internal documentation."""
    name: str
    config: LspServerConfig
    status: ServerStatus = ServerStatus.NOT_STARTED
    client: LspClient | None = None
    proc: Any = None
    versions: dict[str, int] = field(default_factory=dict)   # uri → version
    diag_cache: dict[str, dict] = field(default_factory=dict)  # uri → {"version": N, "items": [...]}
    diag_count_cache: dict[str, int] = field(default_factory=dict)
    slow_streak_ms: int = 0
    crash_count: int = 0
    init_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    pending_requests: list[asyncio.Future[dict]] = field(default_factory=list)
    notif_task: asyncio.Task | None = None


_SpawnProcFn = Callable[
    ["LspManager", str, LspServerConfig, dict, str | None],
    Awaitable[tuple[Any, LspClient]],
]
_SPAWN_PROC_FN: _SpawnProcFn | None = None


def set_spawn_proc_fn(fn: _SpawnProcFn | None) -> None:
    """Internal documentation."""
    global _SPAWN_PROC_FN
    _SPAWN_PROC_FN = fn



def set_event_emit_fn(fn: Callable[[Any], Awaitable[None]] | None) -> None:
    """Internal documentation."""
    global _EMIT_FN
    _EMIT_FN = fn


_EMIT_FN: Callable[[Any], Awaitable[None]] | None = None


async def _emit_event(event: Any) -> None:
    if _EMIT_FN is not None:
        try:
            await _EMIT_FN(event)
        except Exception as e:  # noqa: BLE001
            log.debug("LSP event emit failed: %s", e)



_LSP_LOOP: asyncio.AbstractEventLoop | None = None
_LSP_LOOP_THREAD: Any = None
_LSP_STARTED: bool = False
_LSP_SHUTTING_DOWN: bool = False


def _ensure_lsp_loop_started() -> None:
    """Internal documentation."""
    global _LSP_LOOP, _LSP_LOOP_THREAD, _LSP_STARTED
    if _LSP_STARTED and _LSP_LOOP is not None:
        return
    import threading

    ready = threading.Event()
    _LSP_LOOP = None

    def _run() -> None:
        global _LSP_LOOP
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        _LSP_LOOP = loop
        ready.set()
        try:
            loop.run_forever()
        finally:
            try:
                loop.close()
            except Exception:  # noqa: BLE001
                pass

    t = threading.Thread(target=_run, name="argos-lsp-loop", daemon=True)
    t.start()
    _LSP_LOOP_THREAD = t
    ready.wait(timeout=2.0)
    _LSP_STARTED = True


def request_sync_via_loop(coro_factory, *, timeout: float = 5.0):
    """Internal documentation."""
    _ensure_lsp_loop_started()
    if _LSP_LOOP is None:
        raise RuntimeError("LSP background loop not initialized")
    if _LSP_SHUTTING_DOWN:
        return {"error": "lsp system shutting down"}
    fut = asyncio.run_coroutine_threadsafe(coro_factory(), _LSP_LOOP)
    try:
        return fut.result(timeout=timeout)
    except concurrent.futures.TimeoutError as e:
        return {"error": f"lsp timeout after {timeout}s"}
    except Exception as e:  # noqa: BLE001
        return {"error": f"lsp protocol error: {e}"}


def sync_file_sync(mgr: "LspManager", path: str, content: str, *,
                   timeout: float = 5.0) -> None:
    """Internal documentation."""
    _ensure_lsp_loop_started()
    if _LSP_LOOP is None:
        return
    if _LSP_SHUTTING_DOWN:
        return
    fut = asyncio.run_coroutine_threadsafe(
        mgr.sync_file(path, content), _LSP_LOOP,
    )
    try:
        fut.result(timeout=timeout)
    except Exception as e:  # noqa: BLE001
        log.debug("LSP sync_file failed: %s", e)


def shutdown_lsp_loop() -> None:
    """Internal documentation."""
    global _LSP_LOOP, _LSP_LOOP_THREAD, _LSP_STARTED, _LSP_SHUTTING_DOWN
    _LSP_SHUTTING_DOWN = True
    if _LSP_LOOP is None:
        return
    try:
        _LSP_LOOP.call_soon_threadsafe(_LSP_LOOP.stop)
    except Exception:  # noqa: BLE001
        pass
    if _LSP_LOOP_THREAD is not None:
        _LSP_LOOP_THREAD.join(timeout=2.0)
    _LSP_LOOP = None
    _LSP_LOOP_THREAD = None
    _LSP_STARTED = False
    _LSP_SHUTTING_DOWN = False



class LspManager:
    def __init__(self, config: LspConfig) -> None:
        self._config = config
        self._servers: dict[str, _Server] = {
            name: _Server(name=name, config=sc) for name, sc in config.servers.items()
        }
        self._lock = asyncio.Lock()

    @property
    def config(self) -> LspConfig:
        return self._config

    def get_diagnostics(self, file: str) -> dict | None:
        """Internal documentation."""
        abs_path = str(Path(file).resolve())
        uri = f"file://{quote(abs_path)}"
        all_items: list[dict] = []
        for s in self._servers.values():
            entry = s.diag_cache.get(uri)
            if entry:
                all_items.extend(entry.get("items", []))
        if not all_items:
            return None
        return {"diagnostics": all_items}

    def list_servers(self) -> list[dict]:
        """Internal documentation."""
        result = []
        for s in self._servers.values():
            result.append({
                "name": s.name,
                "command": " ".join(s.config.command),
                "filetypes": list(s.config.filetypes),
                "status": s.status.value,
                "diag_count": sum(s.diag_count_cache.values()),
            })
        return result

    def server_status(self, name: str) -> ServerStatus | None:
        s = self._servers.get(name)
        return s.status if s else None

    def request_sync(
        self, server_name: str, method: str, params: dict | None = None,
        *, timeout: float = _REQUEST_TIMEOUT_S,
    ) -> dict:
        """Internal documentation."""
        return request_sync_via_loop(
            lambda: self._request_sync_impl(server_name, method, params, timeout=timeout),
            timeout=timeout + 5.0,
        )

    async def _request_sync_impl(
        self, server_name: str, method: str, params: dict | None,
        *, timeout: float,
    ) -> dict:
        s = self._servers.get(server_name)
        if s is None:
            return {"error": f"lsp server {server_name!r} not configured"}
        if s.config.disabled:
            return {"error": f"lsp server {server_name!r} disabled"}
        if s.status != ServerStatus.READY:
            ok = await self.start_server(server_name)
            if not ok:
                return {"error": f"lsp server {server_name!r} failed to start"}
        return await self.request(server_name, method, params, timeout=timeout)

    async def request(
        self, server_name: str, method: str, params: dict | None = None,
        *, timeout: float = _REQUEST_TIMEOUT_S,
    ) -> dict:
        """Internal documentation."""
        s = self._servers.get(server_name)
        if s is None:
            return {"error": f"lsp server {server_name!r} not configured"}
        if s.config.disabled or s.status == ServerStatus.DISABLED:
            return {"error": f"lsp server {server_name!r} disabled"}
        if s.status != ServerStatus.READY:
            loop = asyncio.get_event_loop()
            fut: asyncio.Future[dict] = loop.create_future()
            s.pending_requests.append(fut)
            try:
                return await asyncio.wait_for(fut, timeout=10.0)
            except asyncio.TimeoutError:
                try:
                    s.pending_requests.remove(fut)
                except ValueError:
                    pass
                return {"error": f"lsp server {server_name!r} not ready in 10s"}
        assert s.client is not None
        try:
            r = await s.client.send_request(method, params, timeout=timeout)
            s.slow_streak_ms = 0
            return r if isinstance(r, dict) else {"result": r}
        except asyncio.TimeoutError:
            s.slow_streak_ms += int(timeout * 1000)
            if s.slow_streak_ms >= _SLOW_STREAK_LIMIT_MS:
                await self._mark_crashed(s, error=f"slow streak {s.slow_streak_ms}ms")
            return {"error": f"lsp timeout after {timeout}s"}
        except (LspProtocolError, LspStreamClosed, RuntimeError, BrokenPipeError) as e:
            await self._mark_crashed(s, error=str(e))
            return {"error": f"lsp protocol error: {e}"}

    async def start_server(self, server_name: str) -> bool:
        """Internal documentation."""
        s = self._servers.get(server_name)
        if s is None:
            return False
        if s.status in (ServerStatus.READY, ServerStatus.STARTING, ServerStatus.INITIALIZING):
            return True
        async with s.init_lock:
            if s.status == ServerStatus.READY:
                return True
            return await self._spawn_and_initialize(s)

    async def sync_file(self, path: str, content: str) -> None:
        """Internal documentation."""
        if len(content) > _LARGE_FILE_BYTES:
            log.info("LSP skipping large file (>1MB): %s", path)
            return
        p = Path(path)
        ext = p.suffix
        if not ext:
            return
        servers = self._config.get_servers_for_filetype(ext)
        if not servers:
            return
        uri = f"file://{quote(str(p.resolve()))}"
        for server_name, _ in servers:
            s = self._servers.get(server_name)
            if s is None or s.status != ServerStatus.READY:
                continue
            if uri in s.versions:
                s.versions[uri] += 1
                new_version = s.versions[uri]
                prev = _CONTENT_CACHE.get(uri, "")
                range_, new_text = _compute_incremental_range(prev, content)
                change = {"range": range_, "text": new_text} if range_ else {"text": content}
                await s.client.send_notification(  # type: ignore[union-attr]
                    "textDocument/didChange",
                    {
                        "textDocument": {"uri": uri, "version": new_version},
                        "contentChanges": [change],
                    },
                )
            else:
                s.versions[uri] = 1
                await s.client.send_notification(  # type: ignore[union-attr]
                    "textDocument/didOpen",
                    {
                        "textDocument": {
                            "uri": uri,
                            "languageId": _language_id_for_ext(ext),
                            "version": 1,
                            "text": content,
                        },
                    },
                )
            _CONTENT_CACHE[uri] = content

    async def shutdown(self) -> None:
        """Internal documentation."""
        for s in self._servers.values():
            if s.status not in (ServerStatus.READY, ServerStatus.STARTING,
                                ServerStatus.INITIALIZING, ServerStatus.INITIALIZED):
                continue
            try:
                if s.client is not None:
                    try:
                        await asyncio.wait_for(
                            s.client.send_request("shutdown", None, timeout=2.0),
                            timeout=2.0,
                        )
                    except (asyncio.TimeoutError, Exception):  # noqa: BLE001
                        pass
                    try:
                        await s.client.send_notification("exit", None)
                    except Exception:  # noqa: BLE001
                        pass
            except Exception:  # noqa: BLE001
                pass
            if s.proc is not None:
                try:
                    await asyncio.wait_for(s.proc.wait(), timeout=5.0)
                except asyncio.TimeoutError:
                    try:
                        s.proc.kill()
                    except Exception:  # noqa: BLE001
                        pass
                    try:
                        await s.proc.wait()
                    except Exception:  # noqa: BLE001
                        pass
            if s.notif_task is not None:
                s.notif_task.cancel()
                try:
                    await s.notif_task
                except (asyncio.CancelledError, Exception):  # noqa: BLE001
                    pass
            s.status = ServerStatus.SHUTDOWN


    async def _spawn_and_initialize(self, s: _Server) -> bool:
        async with self._lock:
            s.status = ServerStatus.STARTING
            cmd_str = " ".join(s.config.command)
            log.warning("LSP server '%s' running: %s", s.name, cmd_str)
            await _emit_event(LspServerEvent(
                server_name=s.name, status="spawn", command=cmd_str,
                elapsed_ms=0, cwd="", timestamp_ms=_now_ms(),
            ))
            try:
                if _SPAWN_PROC_FN is not None:
                    proc, client = await _SPAWN_PROC_FN(
                        self, s.name, s.config, dict(os.environ), None,
                    )
                else:
                    proc, client = await self._default_spawn(s)
            except FileNotFoundError as e:
                log.warning("lsp server %r not found, disabled: %s", s.name, e)
                s.status = ServerStatus.DISABLED
                await _emit_event(LspServerEvent(
                    server_name=s.name, status="disabled", command=cmd_str,
                    error=str(e), elapsed_ms=0, cwd="", timestamp_ms=_now_ms(),
                ))
                return False
            except OSError as e:
                log.warning("lsp server %r spawn failed, disabled: %s", s.name, e)
                s.status = ServerStatus.DISABLED
                await _emit_event(LspServerEvent(
                    server_name=s.name, status="disabled", command=cmd_str,
                    error=str(e), elapsed_ms=0, cwd="", timestamp_ms=_now_ms(),
                ))
                return False
            s.proc, s.client = proc, client
            try:
                await client.start()
            except Exception as e:  # noqa: BLE001
                await self._mark_crashed(s, error=f"start failed: {e}")
                return False
            s.status = ServerStatus.INITIALIZING
            t0 = _now_ms()
            try:
                await client.send_request("initialize", {
                    "processId": os.getpid(),
                    "rootUri": None,
                    "capabilities": {},
                    "initializationOptions": dict(s.config.init_options),
                }, timeout=5.0)
            except (asyncio.TimeoutError, LspProtocolError, RuntimeError, OSError) as e:
                await self._mark_crashed(s, error=f"initialize failed: {e}")
                return False
            s.status = ServerStatus.INITIALIZED
            try:
                await client.send_notification("initialized", {})
            except Exception:  # noqa: BLE001
                pass
            elapsed = _now_ms() - t0
            s.status = ServerStatus.READY
            for fut in s.pending_requests:
                if not fut.done():
                    fut.set_result({"result": "ready"})
            s.pending_requests.clear()
            self._spawn_notification_listener(s)
            await _emit_event(LspServerEvent(
                server_name=s.name, status="ready", command=cmd_str,
                elapsed_ms=elapsed, cwd="", timestamp_ms=_now_ms(),
            ))
            return True

    async def _default_spawn(self, s: _Server) -> tuple[Any, LspClient]:
        env = dict(os.environ)
        env.update(s.config.env)
        proc = await asyncio.create_subprocess_exec(
            *s.config.command,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
        )
        return proc, LspClient(proc)

    def _spawn_notification_listener(self, s: _Server) -> None:
        """Internal documentation."""
        async def _loop():
            assert s.client is not None
            try:
                async for msg in s.client.notifications():
                    method = msg.get("method", "")
                    params = msg.get("params", {})
                    if method == "textDocument/publishDiagnostics":
                        uri = params.get("uri", "")
                        items = params.get("diagnostics", [])
                        s.diag_cache[uri] = {"version": params.get("version", 0), "items": items}
                        total = len(items)
                        if s.diag_count_cache.get(uri) != total:
                            s.diag_count_cache[uri] = total
                            await _emit_event(LspDiagnosticEvent(
                                server_name=s.name, uri=uri, count=total,
                                severity_counts=_count_severities(items),
                                cached=False, cwd="",
                            ))
                    elif method in ("window/logMessage", "window/showMessage"):
                        log.info("LSP %s: %s", s.name, params.get("message", ""))
                    else:
                        log.info("LSP server %s: unhandled notification %s", s.name, method)
            except asyncio.CancelledError:
                raise
            except Exception as e:  # noqa: BLE001
                log.debug("LSP %s notif listener error: %s", s.name, e)
        s.notif_task = asyncio.create_task(_loop())

    async def _mark_crashed(self, s: _Server, *, error: str) -> None:
        s.status = ServerStatus.CRASHED
        s.crash_count += 1
        log.warning("LSP server %s crashed: %s", s.name, error)
        await _emit_event(LspServerEvent(
            server_name=s.name, status="crash", command=" ".join(s.config.command),
            error=error, elapsed_ms=0, cwd="", timestamp_ms=_now_ms(),
        ))
        async def _retry():
            await asyncio.sleep(_BACKOFF_SECONDS)
            async with s.init_lock:
                if s.status != ServerStatus.CRASHED:
                    return
                ok = await self._spawn_and_initialize(s)
                if not ok:
                    s.status = ServerStatus.DISABLED
                    await _emit_event(LspServerEvent(
                        server_name=s.name, status="disabled",
                        command=" ".join(s.config.command),
                        error="retry failed", elapsed_ms=0, cwd="",
                        timestamp_ms=_now_ms(),
                    ))
        asyncio.create_task(_retry())



def _compute_incremental_range(previous: str, current: str) -> tuple[dict | None, str]:
    """Internal documentation."""
    if previous == current:
        return (
            {"start": {"line": 0, "character": 0}, "end": {"line": 0, "character": 0}},
            "",
        )
    return None, current


def _language_id_for_ext(ext: str) -> str:
    return {
        ".py": "python", ".pyi": "python",
        ".rs": "rust",
        ".ts": "typescript", ".tsx": "typescript",
        ".js": "javascript", ".jsx": "javascript",
        ".go": "go",
    }.get(ext, ext.lstrip("."))


def _count_severities(items: list[dict]) -> dict[str, int]:
    """LSP DiagnosticSeverity: 1=error 2=warning 3=information 4=hint。"""
    counts: dict[str, int] = {"error": 0, "warning": 0, "information": 0, "hint": 0}
    for it in items:
        sev = it.get("severity", 1)
        key = {1: "error", 2: "warning", 3: "information", 4: "hint"}.get(sev, "error")
        counts[key] += 1
    return counts


def _now_ms() -> int:
    import time
    return int(time.time() * 1000)


def _reset_content_cache() -> None:
    """Internal documentation."""
    _CONTENT_CACHE.clear()
