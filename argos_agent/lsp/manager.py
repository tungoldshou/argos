"""LspManager 模块级单例(spec §2.1 / §2.4 / §2.6)。

职责:
- per-server subprocess 生命周期(spawn / initialize / ready / crash / restart / disabled / shutdown)
- 8 状态机(NotStarted / Starting / Initializing / Initialized / Ready / Crashed / Disabled / Shutdown)
- 30s 单次重试 backoff(D9,固定延迟,不指数)
- 版本号单调性(`dict[uri, int]`,per-server,首次 didOpen=1, didChange+=1, 重开也 +=1,**不**复用 1)
- 诊断 cache(`dict[(server_name, uri), DiagEntry]`,server 推就覆盖,**不**做 TTL)
- `sync_file(path, content)` 增量 didChange(走 pygls `text_document_diff`)
- `request(server_name, method, params, *, timeout=5.0)` 路由到对应 server
- 进程级并发安全:`asyncio.Lock` 保护 spawn/kill
- 启动前 stderr 显恶意 command 告警(用户配置 = 用户责任,doc 警示,splash 1 行)
- 把 lifecycle 状态变化 / diagnostics 推到 EventBus(LspServerEvent / LspDiagnosticEvent)
- 并发请求同一 server:10 个 `lsp_*` 同时发 → 全部按 id 路由到正确 future,不串台
"""
from __future__ import annotations

import asyncio
import logging
import os
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Awaitable, Callable, Mapping
from urllib.parse import quote

from argos_agent.lsp.client import LspClient, LspProtocolError, LspStreamClosed, encode_frame
from argos_agent.lsp.config import LspConfig, LspServerConfig
from argos_agent.lsp.events import LspDiagnosticEvent, LspServerEvent

log = logging.getLogger(__name__)


# ── 8 状态机(spec §2.6)────────────────────────────────────────────

class ServerStatus(str, Enum):
    NOT_STARTED = "NotStarted"
    STARTING = "Starting"
    INITIALIZING = "Initializing"
    INITIALIZED = "Initialized"
    READY = "Ready"
    CRASHED = "Crashed"
    DISABLED = "Disabled"
    SHUTDOWN = "Shutdown"


# 30s 固定延迟单次重试(spec D9)
_BACKOFF_SECONDS: float = 30.0

# 单请求 5s 超时(spec §2.6)
_REQUEST_TIMEOUT_S: float = 5.0

# 累计 30s 慢累计上限(spec §2.6)
_SLOW_STREAK_LIMIT_MS: int = 30_000


# 版本号最小阈值同步(给 sync_file 内部用)
_LARGE_FILE_BYTES: int = 1_048_576   # 1 MiB

# 内容缓存:uri → 最近一次 didOpen 全文
_CONTENT_CACHE: dict[str, str] = {}


@dataclass
class _Server:
    """per-server 状态。"""
    name: str
    config: LspServerConfig
    status: ServerStatus = ServerStatus.NOT_STARTED
    client: LspClient | None = None
    proc: Any = None
    versions: dict[str, int] = field(default_factory=dict)   # uri → version
    diag_cache: dict[str, dict] = field(default_factory=dict)  # uri → {"version": N, "items": [...]}
    diag_count_cache: dict[str, int] = field(default_factory=dict)  # uri → 总数(活动栏变化检测)
    slow_streak_ms: int = 0
    crash_count: int = 0
    init_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    pending_requests: list[asyncio.Future[dict]] = field(default_factory=list)
    notif_task: asyncio.Task | None = None


# ── 工厂注入点(test 用) ────────────────────────────────────────────
_SpawnProcFn = Callable[
    ["LspManager", str, LspServerConfig, dict, str | None],
    Awaitable[tuple[Any, LspClient]],
]
_SPAWN_PROC_FN: _SpawnProcFn | None = None


def set_spawn_proc_fn(fn: _SpawnProcFn | None) -> None:
    """测试用:替换默认 _spawn_proc 实现(in-process fake)。"""
    global _SPAWN_PROC_FN
    _SPAWN_PROC_FN = fn


# ── EventBus 注入桥(spec §2.5)────────────────────────────────────

def set_event_emit_fn(fn: Callable[[Any], Awaitable[None]] | None) -> None:
    """测试/生产:注入 event emit 桥(默认 no-op,生产由 tui app 注入)。"""
    global _EMIT_FN
    _EMIT_FN = fn


_EMIT_FN: Callable[[Any], Awaitable[None]] | None = None


async def _emit_event(event: Any) -> None:
    if _EMIT_FN is not None:
        try:
            await _EMIT_FN(event)
        except Exception as e:  # noqa: BLE001
            log.debug("LSP event emit failed: %s", e)


# ── LspManager 主类 ────────────────────────────────────────────────

class LspManager:
    def __init__(self, config: LspConfig) -> None:
        self._config = config
        self._servers: dict[str, _Server] = {
            name: _Server(name=name, config=sc) for name, sc in config.servers.items()
        }
        self._lock = asyncio.Lock()   # 进程级 spawn/kill 串行

    @property
    def config(self) -> LspConfig:
        return self._config

    def get_diagnostics(self, file: str) -> dict | None:
        """lsp_diagnostics 工具用:从所有 server cache 合并该 file 的诊断。"""
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
        """TUI `/lsp` 列当前生效 server: name / command / filetype / status / diag 计数。"""
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

    async def request(
        self, server_name: str, method: str, params: dict | None = None,
        *, timeout: float = _REQUEST_TIMEOUT_S,
    ) -> dict:
        """路由到 server_name,发 JSON-RPC request,等 response。

        - server 不存在 / disabled → 返 `{"error": "lsp server 'X' disabled"}`
        - state != Ready → 挂起到 pending_requests,等状态变 Ready 后 set;>10s 报 timeout
        - 单 request 5s 超时(spec D10);累计 30s 慢 → 走 crash 路径
        """
        s = self._servers.get(server_name)
        if s is None:
            return {"error": f"lsp server {server_name!r} not configured"}
        if s.config.disabled or s.status == ServerStatus.DISABLED:
            return {"error": f"lsp server {server_name!r} disabled"}
        if s.status != ServerStatus.READY:
            # 挂起等 Ready(>10s 报 timeout,spec §4.4)
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
        # 走真 client
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
        """显式起 server(lazy start 也走此路径)。返 True=起好,False=失败。"""
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
        """write_file/edit_file 触发点:host loop 调。

        1. 大文件跳过(>1MB,spec §2.4)
        2. 找 file ext 对应的 server(无 → no-op)
        3. 首次 → didOpen(version=1, content=全文)
           后续 → didChange(增量 range, version+=1)
        4. 写 stdin(用对应 server.client.send_notification)
        """
        # 大文件跳过(spec §2.4:>1MB 跳过 LSP,不发 didOpen)
        if len(content) > _LARGE_FILE_BYTES:
            log.info("LSP skipping large file (>1MB): %s", path)
            return
        p = Path(path)
        ext = p.suffix
        if not ext:
            return
        servers = self._config.get_servers_for_filetype(ext)
        if not servers:
            return   # 无 server 服务此 ext(诚实不假装)
        uri = f"file://{quote(str(p.resolve()))}"
        for server_name, _ in servers:
            s = self._servers.get(server_name)
            if s is None or s.status != ServerStatus.READY:
                continue   # server 未就绪,跳过(下个 lsp_* 触发 didOpen 重发)
            if uri in s.versions:
                # didChange(增量):version += 1,**不**复用 1(spec §2.4 单调性)
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
                # didOpen(首次):version=1
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
        """session 结束:逐 server 发 shutdown + exit + 5s wait。"""
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

    # ── 内部 ─────────────────────────────────────────────────────

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
            # 唤醒所有 pending_requests
            for fut in s.pending_requests:
                if not fut.done():
                    fut.set_result({"result": "ready"})
            s.pending_requests.clear()
            # 起 notification listener(diagnostics 路由)
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
        """后台协程:持续收 server 推的 notification(diagnostics / logMessage / 等)。"""
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
        # 30s 单次固定延迟重试;重试再失败 → Disabled
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


# ── 增量 didChange range 计算(spec D6)────────────────────────────

def _compute_incremental_range(previous: str, current: str) -> tuple[dict | None, str]:
    """用最小依赖算 range + text。简化:整文同则空 range,否则整文替换(None 表示无 range)。

    spec D6 要求增量:本期 v1 简化 — 整文变化时返 (None, current) 让 caller 走全量 {text: current},
    文件相同时返 (range, "")(空 text = 删除)。
    后续 v1.1 引入 diff-match-patch 行级 diff。
    """
    if previous == current:
        return (
            {"start": {"line": 0, "character": 0}, "end": {"line": 0, "character": 0}},
            "",
        )
    return None, current   # 整文替换


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
    """测试用:清空 _CONTENT_CACHE。"""
    _CONTENT_CACHE.clear()
