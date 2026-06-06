"""HTTP/SSE server(stdlib asyncio.start_server + 手写 HTTP/1.1)spec §2.5。

5 端点(本期 #5a):
  GET  /health
  GET  /version
  POST /sessions
  POST /sessions/{id}/heartbeat
  DELETE /sessions/{id}
  GET  /runs
  POST /runs
  GET  /runs/{id}
  GET  /runs/{id}/events?since=N  (SSE)
  POST /runs/{id}/pause
  POST /runs/{id}/resume
  POST /runs/{id}/cancel
  POST /runs/{id}/approval/{call_id}

注:#5a 单 TUI 限定 → 所有 session 都 write-capable(无 read-only 降级)。
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from argos_agent.daemon.manager import RunManager
from argos_agent.daemon.protocol import (
    CODE_BAD_REQUEST, CODE_BUSY, CODE_INTERNAL, CODE_INVALID_TRANSITION,
    CODE_MISSING_SESSION, CODE_NOT_FOUND, HEADER_SESSION,
)
from argos_agent.daemon.sessions import SessionRegistry

log = logging.getLogger(__name__)


_HTTP_REASONS = {
    200: "OK", 201: "Created", 202: "Accepted", 204: "No Content",
    400: "Bad Request", 401: "Unauthorized", 404: "Not Found",
    409: "Conflict", 500: "Internal Server Error", 503: "Service Unavailable",
}


class DaemonHTTPServer:
    """Unix socket HTTP server,async。"""

    def __init__(self, *, manager: RunManager, socket_path: Path,
                 session_timeout_s: float = 30.0,
                 registry=None, worktree=None):
        self._manager = manager
        self._socket_path = Path(socket_path)
        self._sessions = SessionRegistry(heartbeat_timeout_s=session_timeout_s)
        # #5b 扩展(向后兼容,缺省时建空):注册表 + worktree manager
        if registry is None:
            from argos_agent.daemon.registry import RunRegistry
            registry = RunRegistry()
        if worktree is None:
            from argos_agent.daemon.worktree import WorktreeManager
            worktree = WorktreeManager()
        self._registry = registry
        self._worktree = worktree
        self._server: asyncio.base_events.Server | None = None
        self._started_at: float = 0.0

    @property
    def registry(self):
        return self._registry

    @property
    def worktree(self):
        return self._worktree

    @property
    def socket_path(self) -> Path:
        return self._socket_path

    @property
    def sessions(self) -> SessionRegistry:
        return self._sessions

    async def start(self) -> None:
        self._socket_path.parent.mkdir(parents=True, exist_ok=True)
        if self._socket_path.exists():
            self._socket_path.unlink()
        self._server = await asyncio.start_unix_server(
            self._handle_connection, path=str(self._socket_path),
        )
        # 0600 权限
        try:
            self._socket_path.chmod(0o600)
        except OSError:
            pass
        self._started_at = time.time()
        log.info("daemon server started, socket=%s", self._socket_path)

    async def stop(self) -> None:
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()
            self._server = None
        try:
            self._socket_path.unlink()
        except FileNotFoundError:
            pass

    # ── connection handling ──────────────────────────────────────────

    async def _handle_connection(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        try:
            request_line = await reader.readline()
            if not request_line:
                writer.close()
                return
            try:
                method, target, _ = request_line.decode("latin-1").rstrip("\r\n").split(" ", 2)
            except ValueError:
                await self._send_error(writer, 400, CODE_BAD_REQUEST, "bad request line")
                return
            # 读 headers
            headers: dict[str, str] = {}
            while True:
                line = await reader.readline()
                if line in (b"\r\n", b"\n", b""):
                    break
                try:
                    k, v = line.decode("latin-1").rstrip("\r\n").split(":", 1)
                    headers[k.strip().lower()] = v.strip()
                except ValueError:
                    continue
            # 读 body(Content-Length)
            body = b""
            cl = headers.get("content-length")
            if cl:
                try:
                    n = int(cl)
                    body = await reader.readexactly(n)
                except (ValueError, asyncio.IncompleteReadError):
                    pass
            # 拆 path + query
            parts = urlsplit(target)
            path = parts.path
            query = parse_qs(parts.query)
            await self._dispatch(writer, method, path, headers, body, query)
        except Exception as e:  # noqa: BLE001
            log.warning("connection error: %s", e)
        finally:
            try:
                writer.close()
            except Exception:  # noqa: BLE001
                pass

    # ── routing ──────────────────────────────────────────────────────

    async def _dispatch(self, writer, method, path, headers, body, query):
        try:
            if method == "GET" and path == "/health":
                return await self._handle_health(writer, headers)
            if method == "GET" and path == "/version":
                return await self._send_json(writer, 200, {"daemon": "0.2.0", "protocol": 1})
            if method == "POST" and path == "/sessions":
                return await self._handle_create_session(writer)
            if method == "POST" and path.startswith("/sessions/") and path.endswith("/heartbeat"):
                sid = path[len("/sessions/"):-len("/heartbeat")]
                return await self._handle_heartbeat(writer, sid)
            if method == "DELETE" and path.startswith("/sessions/"):
                sid = path[len("/sessions/"):]
                return await self._handle_delete_session(writer, sid)
            if method == "GET" and path == "/runs":
                return await self._handle_list_runs(writer, headers, query)
            if method == "POST" and path == "/runs":
                return await self._handle_create_run(writer, headers, body)
            if path.startswith("/runs/"):
                rest = path[len("/runs/"):]
                if method == "GET" and rest.endswith("/events"):
                    rid = rest[:-len("/events")]
                    return await self._handle_sse(writer, headers, rid, query)
                if method == "POST" and rest.endswith("/focus"):
                    rid = rest[:-len("/focus")]
                    return await self._handle_focus(writer, headers, rid)
                if method == "POST" and rest.endswith("/pause"):
                    rid = rest[:-len("/pause")]
                    return await self._handle_pause(writer, headers, rid)
                if method == "POST" and rest.endswith("/resume"):
                    rid = rest[:-len("/resume")]
                    return await self._handle_resume(writer, headers, rid)
                if method == "POST" and rest.endswith("/cancel"):
                    rid = rest[:-len("/cancel")]
                    return await self._handle_cancel(writer, headers, rid)
                if method == "POST" and "/approval/" in rest:
                    rid, call_id = rest.split("/approval/", 1)
                    return await self._handle_approval(writer, headers, rid, call_id, body)
                if method == "GET":
                    return await self._handle_get_run(writer, headers, rest)
                return await self._send_error(writer, 404, CODE_NOT_FOUND,
                                              f"no route for {method} {path}")
            return await self._send_error(writer, 404, CODE_NOT_FOUND,
                                          f"no route for {method} {path}")
        except Exception as e:  # noqa: BLE001
            log.exception("dispatch error: %s", e)
            return await self._send_error(writer, 500, CODE_INTERNAL, str(e))

    # ── Session helpers ──────────────────────────────────────────────

    async def _require_session(self, writer, headers) -> str | None:
        sid = headers.get(HEADER_SESSION.lower())
        if not sid:
            await self._send_error(writer, 400, CODE_MISSING_SESSION, "missing X-Argos-Session header")
            return None
        if not self._sessions.is_alive(sid):
            await self._send_error(writer, 401, CODE_MISSING_SESSION, "session expired or unknown")
            return None
        # 续命
        await self._sessions.heartbeat(sid)
        return sid

    # ── Handlers ─────────────────────────────────────────────────────

    async def _handle_health(self, writer, headers):
        sid = headers.get(HEADER_SESSION.lower())
        if sid and self._sessions.is_alive(sid):
            others = self._sessions.other_sessions(sid)
        else:
            others = self._sessions.list_active()
        await self._send_json(writer, 200, {
            "status": "ok",
            "uptime_s": int(time.time() - self._started_at) if self._started_at else 0,
            "other_tuis": len(others),
        })

    async def _handle_create_session(self, writer):
        rec = await self._sessions.create()
        await self._send_json(writer, 201, {"session_id": rec.session_id})

    async def _handle_heartbeat(self, writer, sid):
        ok = await self._sessions.heartbeat(sid)
        if not ok:
            return await self._send_error(writer, 404, CODE_NOT_FOUND, "session not found")
        await self._send_json(writer, 200, {
            "active_tuis": self._sessions.active_count(),
        })

    async def _handle_delete_session(self, writer, sid):
        await self._sessions.remove(sid)
        await self._send_json(writer, 204, {"ok": True})

    async def _handle_list_runs(self, writer, headers, query):
        if (sid := await self._require_session(writer, headers)) is None:
            return
        state_filter = None
        if "state" in query and query["state"]:
            state_filter = query["state"][0]
        runs = self._manager.list_runs(state=state_filter)
        # #5b 合并 registry 的 cost/worktree/focus 字段
        for r in runs:
            entry = self._registry.get(r["run_id"])
            if entry is not None:
                r["tokens_in"] = entry.tokens_in
                r["tokens_out"] = entry.tokens_out
                r["cost_usd"] = entry.cost_usd
                r["worktree_path"] = entry.worktree_path
                r["focus_session_id"] = entry.focus_session_id
        await self._send_json(writer, 200, runs)

    async def _handle_create_run(self, writer, headers, body):
        if (sid := await self._require_session(writer, headers)) is None:
            return
        try:
            data = json.loads(body.decode("utf-8") or "{}")
        except json.JSONDecodeError:
            return await self._send_error(writer, 400, CODE_BAD_REQUEST, "invalid JSON body")
        goal = data.get("goal")
        if not goal or not isinstance(goal, str):
            return await self._send_error(writer, 400, CODE_BAD_REQUEST, "missing goal")
        # #5b 并发满 → 503(spec §5.2)
        if not self._registry.has_capacity():
            return await self._send_error(
                writer, 503, CODE_BUSY,
                f"max_concurrent_runs_reached "
                f"(max={self._registry.max_concurrent}, "
                f"active={self._registry.active_count})",
            )
        # 抢 slot(同步路径,has_capacity 已 check,不该阻塞)
        try:
            await asyncio.wait_for(self._registry.acquire_slot(), timeout=0.01)
        except asyncio.TimeoutError:
            return await self._send_error(
                writer, 503, CODE_BUSY,
                f"max_concurrent_runs_reached "
                f"(max={self._registry.max_concurrent}, "
                f"active={self._registry.active_count})",
            )
        try:
            run_id = await self._manager.create_run(
                goal=goal,
                workspace=data.get("workspace", ""),
                model=data.get("model", ""),
                approval_level=data.get("approval_level", "confirm"),
            )
        except Exception:
            self._registry.release_slot()
            raise
        # #5b worktree(若请求 isolation=worktree)
        wt_path = None
        workspace = data.get("workspace", "")
        if data.get("isolation") == "worktree" and workspace:
            try:
                wt_path = self._worktree.create(run_id=run_id, workspace=workspace)
            except Exception as e:  # noqa: BLE001
                self._registry.release_slot()
                return await self._send_error(
                    writer, 503, "worktree_failed", str(e),
                )
        # 注册到 registry
        await self._registry.register(
            run_id=run_id, goal=goal, workspace=workspace, worktree_path=wt_path,
        )
        await self._send_json(writer, 201, {"run_id": run_id})

    async def _handle_get_run(self, writer, headers, run_id):
        if (sid := await self._require_session(writer, headers)) is None:
            return
        entry = self._manager.get_run(run_id)
        if entry is None:
            return await self._send_error(writer, 404, CODE_NOT_FOUND, "run not found")
        # #5b 优先从 registry 读(可能更精确)
        reg_entry = self._registry.get(run_id)
        body = {
            "run_id": run_id,
            "state": (reg_entry.state if reg_entry else entry.state),
            "events_count": self._manager.events_count(run_id),
            "last_event_seq": entry.last_event_seq,
            "goal": entry.goal,
            "workspace": entry.workspace,
        }
        if reg_entry is not None:
            body["tokens_in"] = reg_entry.tokens_in
            body["tokens_out"] = reg_entry.tokens_out
            body["cost_usd"] = reg_entry.cost_usd
            body["worktree_path"] = reg_entry.worktree_path
            body["focus_session_id"] = reg_entry.focus_session_id
        await self._send_json(writer, 200, body)

    async def _handle_pause(self, writer, headers, run_id):
        if (sid := await self._require_session(writer, headers)) is None:
            return
        ok = await self._manager.request_pause(run_id)
        if not ok:
            return await self._send_error(writer, 409, CODE_INVALID_TRANSITION,
                                          "run is not running (cannot pause)")
        await self._send_json(writer, 202, {"state": "pause_requested"})

    async def _handle_resume(self, writer, headers, run_id):
        if (sid := await self._require_session(writer, headers)) is None:
            return
        ok = await self._manager.request_resume(run_id)
        if not ok:
            return await self._send_error(writer, 409, CODE_INVALID_TRANSITION,
                                          "run is not paused/suspended (cannot resume)")
        await self._send_json(writer, 202, {"state": "resume_requested"})

    async def _handle_cancel(self, writer, headers, run_id):
        if (sid := await self._require_session(writer, headers)) is None:
            return
        ok = await self._manager.request_cancel(run_id)
        if not ok:
            return await self._send_error(writer, 409, CODE_INVALID_TRANSITION,
                                          "run is in terminal state (cannot cancel)")
        await self._send_json(writer, 202, {"state": "cancel_requested"})

    async def _handle_focus(self, writer, headers, run_id):
        """#5b POST /runs/{id}/focus:TUI 告诉 daemon "此 run 是我的 active 焦点"。

        暂不限制 owner/observer(T3 补 _require_owner)。"""
        if (sid := await self._require_session(writer, headers)) is None:
            return
        if self._registry.get(run_id) is None:
            return await self._send_error(writer, 404, CODE_NOT_FOUND, "run not found")
        self._registry.set_focus(run_id=run_id, session_id=sid)
        await self._send_json(writer, 200, {
            "run_id": run_id,
            "focus_session_id": sid,
        })

    async def _handle_approval(self, writer, headers, run_id, call_id, body):
        if (sid := await self._require_session(writer, headers)) is None:
            return
        try:
            data = json.loads(body.decode("utf-8") or "{}")
        except json.JSONDecodeError:
            return await self._send_error(writer, 400, CODE_BAD_REQUEST, "invalid JSON body")
        decision = data.get("decision")
        if decision not in ("approve", "deny"):
            return await self._send_error(writer, 400, CODE_BAD_REQUEST,
                                          "decision must be 'approve' or 'deny'")
        # 投 SSE 事件给 worker
        await self._manager.fanout(run_id, {
            "kind": "approval_response",
            "call_id": call_id,
            "decision": decision,
            "ts": time.time(),
        })
        await self._send_json(writer, 200, {
            "call_id": call_id, "decision": decision, "state": "applied",
        })

    # ── SSE ──────────────────────────────────────────────────────────

    async def _handle_sse(self, writer, headers, run_id, query):
        if (sid := await self._require_session(writer, headers)) is None:
            return
        if not self._manager.get_run(run_id):
            return await self._send_error(writer, 404, CODE_NOT_FOUND, "run not found")
        # 解析 ?since=N
        since = 0
        if "since" in query and query["since"]:
            try:
                since = int(query["since"][0])
            except (ValueError, IndexError):
                since = 0
        writer.write(
            b"HTTP/1.1 200 OK\r\n"
            b"Content-Type: text/event-stream\r\n"
            b"Cache-Control: no-cache\r\n"
            b"Connection: keep-alive\r\n"
            b"X-Accel-Buffering: no\r\n\r\n"
        )
        await writer.drain()
        # replay 起始
        try:
            for ev in self._manager.store.replay(run_id, since_seq=since):
                await self._send_sse_event(writer, ev)
        except Exception as e:  # noqa: BLE001
            log.warning("SSE replay error for %s: %s", run_id, e)
        # 订阅新事件
        q = self._manager.subscribe(run_id)
        try:
            while True:
                try:
                    ev = await asyncio.wait_for(q.get(), timeout=15.0)
                except asyncio.TimeoutError:
                    try:
                        writer.write(b": keepalive\n\n")
                        await writer.drain()
                    except (ConnectionResetError, BrokenPipeError):
                        break
                    continue
                try:
                    await self._send_sse_event(writer, ev)
                except (ConnectionResetError, BrokenPipeError):
                    break
        except (ConnectionResetError, BrokenPipeError, asyncio.CancelledError):
            pass
        finally:
            self._manager.unsubscribe(run_id, q)
            try:
                writer.close()
            except Exception:  # noqa: BLE001
                pass

    async def _send_sse_event(self, writer, ev: dict):
        kind = ev.get("kind", "message")
        data = json.dumps(ev, ensure_ascii=False)
        writer.write(f"event: {kind}\ndata: {data}\n\n".encode("utf-8"))
        await writer.drain()

    # ── low-level response ───────────────────────────────────────────

    async def _send_json(self, writer, status: int, body):
        payload = json.dumps(body, ensure_ascii=False).encode("utf-8")
        reason = _HTTP_REASONS.get(status, "OK")
        head = (
            f"HTTP/1.1 {status} {reason}\r\n"
            f"Content-Type: application/json\r\n"
            f"Content-Length: {len(payload)}\r\n"
            f"Connection: close\r\n\r\n"
        ).encode("latin-1")
        writer.write(head)
        writer.write(payload)
        await writer.drain()
        try:
            writer.close()
        except Exception:  # noqa: BLE001
            pass

    async def _send_error(self, writer, status: int, code: str, message: str):
        await self._send_json(writer, status, {"error": message, "code": code})
