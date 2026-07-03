"""Internal documentation."""
from __future__ import annotations

import asyncio
import json
import logging
import time
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from argos.app_factory import build_run_stack
from argos.daemon.conductor_supervisor import CONDUCTOR_RUN_ID
from argos.daemon.manager import RunManager
from argos.daemon.state_machine import TERMINAL_STATES
from argos.i18n import t
from argos.daemon.protocol import (
    CODE_BAD_REQUEST, CODE_BUSY, CODE_INTERNAL, CODE_INVALID_TRANSITION,
    CODE_MISSING_SESSION, CODE_NOT_FOUND, CODE_SESSION_READONLY, HEADER_SESSION,
)
from argos.daemon.sessions import SessionRegistry

log = logging.getLogger(__name__)


_HTTP_REASONS = {
    200: "OK", 201: "Created", 202: "Accepted", 204: "No Content",
    400: "Bad Request", 401: "Unauthorized", 404: "Not Found",
    409: "Conflict", 500: "Internal Server Error", 503: "Service Unavailable",
}


_NO_KEY = object()


class DaemonHTTPServer:
    """Unix socket HTTP server,async。"""

    def __init__(self, *, manager: RunManager, socket_path: Path,
                 session_timeout_s: float = 30.0,
                 registry=None, worktree=None,
                 loop_factory=None, gate=None,
                 components=None, ledger_store=None,
                 conductor_supervisor=None):
        """Internal documentation."""
        self._manager = manager
        self._socket_path = Path(socket_path)
        self._sessions = SessionRegistry(heartbeat_timeout_s=session_timeout_s)
        if registry is None:
            from argos.daemon.registry import RunRegistry
            registry = RunRegistry()
        if worktree is None:
            from argos.daemon.worktree import WorktreeManager
            worktree = WorktreeManager()
        self._registry = registry
        self._worktree = worktree
        self._components = components
        self._loop_factory = loop_factory
        self._gate = gate
        self._server: asyncio.base_events.Server | None = None
        self._started_at: float = 0.0
        self._workers: dict[str, "RunWorker"] = {}
        self._ledger_store = ledger_store
        self._conductor = conductor_supervisor
        self._dream_pipeline = None
        self._dream_starting: bool = False
        if conductor_supervisor is not None:
            conductor_supervisor._dream_starter = self._autonomous_dream_starter

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
            body = b""
            cl = headers.get("content-length")
            if cl:
                try:
                    n = int(cl)
                    body = await reader.readexactly(n)
                except (ValueError, asyncio.IncompleteReadError):
                    pass
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
                from argos import __version__ as _argos_version
                from argos.protocol import PROTOCOL_VERSION
                return await self._send_json(
                    writer, 200, {
                        "daemon": _argos_version, "protocol": PROTOCOL_VERSION,
                        "started_at": self._started_at,
                    }
                )
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
                if method == "POST" and rest.endswith("/suspend"):
                    rid = rest[:-len("/suspend")]
                    return await self._handle_suspend(writer, headers, rid)
                if method == "POST" and rest.endswith("/resume"):
                    rid = rest[:-len("/resume")]
                    return await self._handle_resume(writer, headers, rid)
                if method == "POST" and rest.endswith("/cancel"):
                    rid = rest[:-len("/cancel")]
                    return await self._handle_cancel(writer, headers, rid)
                if method == "POST" and "/approval/" in rest:
                    rid, call_id = rest.split("/approval/", 1)
                    return await self._handle_approval(writer, headers, rid, call_id, body)
                if method == "POST" and "/plan_decision" in rest:
                    rid = rest.split("/plan_decision")[0]
                    return await self._handle_plan_decision(writer, headers, rid, body)
                if method == "GET" and rest.endswith("/ledger"):
                    rid = rest[:-len("/ledger")]
                    return await self._handle_get_ledger(writer, headers, rid)
                if method == "POST" and rest.endswith("/undo"):
                    rid = rest[:-len("/undo")]
                    return await self._handle_undo(writer, headers, rid, body)
                if method == "GET":
                    return await self._handle_get_run(writer, headers, rest)
                return await self._send_error(writer, 404, CODE_NOT_FOUND,
                                              f"no route for {method} {path}")
            if method == "POST" and path == "/orders":
                return await self._handle_create_order(writer, headers, body)
            if method == "GET" and path == "/orders":
                return await self._handle_list_orders(writer, headers)
            if method == "DELETE" and path.startswith("/orders/"):
                order_id = path[len("/orders/"):]
                return await self._handle_delete_order(writer, headers, order_id)
            if path.startswith("/suggestions/"):
                rest = path[len("/suggestions/"):]
                if method == "POST" and rest.endswith("/confirm"):
                    sid_part = rest[:-len("/confirm")]
                    return await self._handle_confirm_suggestion(writer, headers, sid_part)
                if method == "POST" and rest.endswith("/dismiss"):
                    sid_part = rest[:-len("/dismiss")]
                    return await self._handle_dismiss_suggestion(writer, headers, sid_part)
            if method == "GET" and path == "/suggestions":
                return await self._handle_list_suggestions(writer, headers)
            if method == "POST" and path == "/dream/run":
                return await self._handle_dream_run(writer, headers)
            if method == "GET" and path == "/dream/report":
                return await self._handle_dream_report(writer, headers)
            return await self._send_error(writer, 404, CODE_NOT_FOUND,
                                          f"no route for {method} {path}")
        except Exception as e:  # noqa: BLE001
            log.exception("dispatch error: %s", e)
            return await self._send_error(writer, 500, CODE_INTERNAL, str(e))

    # ── Session helpers ──────────────────────────────────────────────

    async def _require_session(self, writer, headers) -> str | None:
        try:
            await self._sessions.reap_expired()
        except Exception as _re:  # noqa: BLE001
            log.warning("session reap 失败(忽略): %s", _re)
        sid = headers.get(HEADER_SESSION.lower())
        if not sid:
            await self._send_error(writer, 400, CODE_MISSING_SESSION, "missing X-Argos-Session header")
            return None
        if not self._sessions.is_alive(sid):
            await self._send_error(writer, 401, CODE_MISSING_SESSION, "session expired or unknown")
            return None
        await self._sessions.heartbeat(sid)
        return sid

    async def _require_owner(self, writer, headers) -> str | None:
        """Internal documentation."""
        sid = await self._require_session(writer, headers)
        if sid is None:
            return None
        rec = self._sessions.get(sid)
        if rec is None or rec.role != "owner":
            await self._send_error(
                writer, 403, CODE_SESSION_READONLY,
                "session is read-only observer (not owner);write operations require owner",
            )
            return None
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
        new_owner = await self._sessions.promote_oldest_observer_after_remove(sid)
        await self._send_json(writer, 204, {"ok": True, "promoted_to": new_owner})

    async def _handle_list_runs(self, writer, headers, query):
        if (sid := await self._require_session(writer, headers)) is None:
            return
        state_filter = None
        if "state" in query and query["state"]:
            state_filter = query["state"][0]
        runs = self._manager.list_runs(state=state_filter)
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
        if (sid := await self._require_owner(writer, headers)) is None:
            return
        try:
            data = json.loads(body.decode("utf-8") or "{}")
        except json.JSONDecodeError:
            return await self._send_error(writer, 400, CODE_BAD_REQUEST, "invalid JSON body")
        goal = data.get("goal")
        if not goal or not isinstance(goal, str):
            return await self._send_error(writer, 400, CODE_BAD_REQUEST, "missing goal")
        if self._loop_factory is _NO_KEY:
            return await self._send_error(
                writer, 503, "no_worker_key",
                t("daemon.srv.no_key_run"),
            )

        if not self._registry.has_capacity():
            return await self._send_error(
                writer, 503, CODE_BUSY,
                f"max_concurrent_runs_reached "
                f"(max={self._registry.max_concurrent}, "
                f"active={self._registry.active_count})",
            )
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
                session_id=sid,
            )
        except Exception:
            self._registry.release_slot()
            raise
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
        await self._registry.register(
            run_id=run_id, goal=goal, workspace=workspace, worktree_path=wt_path,
        )

        effective_ws_str = wt_path or (workspace if workspace else None)
        from argos.daemon.worker import RunWorker
        approval_timeout_s = float(data.get("approval_timeout_s", 60.0))
        from argos.daemon.attachments_wire import decode_attachments
        run_attachments = decode_attachments(data.get("attachments"))

        run_snapshot = None
        if effective_ws_str:
            try:
                from argos.core.snapshot import RunSnapshot, SNAPSHOT_ROOT
                _ws_snap = Path(effective_ws_str).expanduser().resolve()
                if _ws_snap.exists():
                    _snap_path = SNAPSHOT_ROOT / f"run-{run_id}.tar"
                    run_snapshot = RunSnapshot.take(_ws_snap, _snap_path)
            except Exception as _snap_err:  # noqa: BLE001
                log.warning("server: run 起点快照失败(undo 将不可用): %s", _snap_err)

        _verify_cmd: str | None = data.get("verify_cmd") or None

        _trust_level_str = data.get("trust_level")

        def _apply_trust_to_gate(gate: "Any") -> None:
            """Internal documentation."""
            if not _trust_level_str:
                return
            try:
                from argos.permissions.trust_dial import TrustLevel
                tl = TrustLevel[_trust_level_str]
                gate.set_trust_level(tl)
            except KeyError:
                log.warning(
                    "server: create_run trust_level=%r 不是有效 TrustLevel 枚举名,"
                    " 忽略并沿用默认 approval_level 语义。",
                    _trust_level_str,
                )
            except Exception as _te:  # noqa: BLE001
                log.warning("server: trust_level 应用失败,诚实降级: %s", _te)

        if self._components is not None:
            effective_ws_path = (
                Path(effective_ws_str).expanduser().resolve()
                if effective_ws_str else None
            )
            run_stack = build_run_stack(
                self._components,
                workspace=effective_ws_path,
                session_id=f"run-{run_id}",
                verify_cmd=_verify_cmd,
            )
            _apply_trust_to_gate(run_stack.gate)
            worker = RunWorker(
                run_id=run_id,
                manager=self._manager,
                loop_factory=run_stack.loop_factory,
                registry=self._registry,
                worktree=self._worktree,
                gate=run_stack.gate,
                run_stack_close=run_stack.close,
                approval_timeout_s=approval_timeout_s,
                ledger_store=self._ledger_store,
                snapshot=run_snapshot,
                attachments=run_attachments,
            )
            self._spawn_worker(worker, run_id, name=f"run-{run_id}")
        elif callable(self._loop_factory):
            run_loop_factory = self._make_run_loop_factory(effective_ws_str)
            if self._gate is not None:
                if _trust_level_str:
                    log.warning(
                        "create_run: trust_level=%s 写入【全局共享】gate(向后兼容路径),"
                        "将影响共享该 gate 的所有并发 run;per-run 隔离请走 components 路径",
                        _trust_level_str,
                    )
                _apply_trust_to_gate(self._gate)

            worker = RunWorker(
                run_id=run_id,
                manager=self._manager,
                loop_factory=run_loop_factory,
                registry=self._registry,
                worktree=self._worktree,
                gate=self._gate,
                approval_timeout_s=approval_timeout_s,
                ledger_store=self._ledger_store,
                snapshot=run_snapshot,
                attachments=run_attachments,
            )
            self._spawn_worker(worker, run_id, name=f"run-{run_id}")
        else:
            self._registry.release_slot()

        await self._send_json(writer, 201, {"run_id": run_id})

    def _spawn_worker(self, worker: "RunWorker", run_id: str, *, name: str) -> "asyncio.Task":
        """Internal documentation."""
        self._workers[run_id] = worker
        task = asyncio.create_task(worker.run(), name=name)
        task.add_done_callback(lambda _t, rid=run_id: self._workers.pop(rid, None))
        return task

    def _make_run_loop_factory(self, workspace: str | None):
        """Internal documentation."""
        from pathlib import Path

        base_factory = self._loop_factory

        if not workspace:
            return base_factory

        ws_path = Path(workspace).expanduser().resolve()
        ws_path.mkdir(parents=True, exist_ok=True)

        def _run_specific_factory():
            loop = base_factory()
            loop._workspace = ws_path
            loop._verify_dir = ws_path
            return loop

        return _run_specific_factory

    async def _handle_get_run(self, writer, headers, run_id):
        if (sid := await self._require_session(writer, headers)) is None:
            return
        entry = self._manager.get_run(run_id)
        if entry is None:
            return await self._send_error(writer, 404, CODE_NOT_FOUND, "run not found")
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
        if (sid := await self._require_owner(writer, headers)) is None:
            return
        ok = await self._manager.request_pause(run_id)
        if not ok:
            return await self._send_error(writer, 409, CODE_INVALID_TRANSITION,
                                          "run is not running (cannot pause)")
        await self._send_json(writer, 202, {"state": "pause_requested"})

    async def _handle_suspend(self, writer, headers, run_id):
        """Internal documentation."""
        if (sid := await self._require_owner(writer, headers)) is None:
            return
        ok = await self._manager.request_suspend(run_id)
        if not ok:
            return await self._send_error(writer, 409, CODE_INVALID_TRANSITION,
                                          "run is not running (cannot suspend)")
        await self._send_json(writer, 202, {"state": "suspend_requested"})

    async def _handle_resume(self, writer, headers, run_id):
        if (sid := await self._require_owner(writer, headers)) is None:
            return
        # Check pre-resume state to decide whether we need to spawn a new worker.
        entry = self._manager.get_run(run_id)
        if entry is None:
            return await self._send_error(writer, 404, CODE_NOT_FOUND, "run not found")
        was_suspended = entry.state == "suspended"

        ok = await self._manager.request_resume(run_id)
        if not ok:
            return await self._send_error(writer, 409, CODE_INVALID_TRANSITION,
                                          "run is not paused/suspended (cannot resume)")

        # Paused runs have a live worker blocked on pause_event.wait() — setting the
        # event above is sufficient.  Suspended runs may have no live worker (e.g.
        # after a daemon restart).  Spawn one from the persisted metadata + checkpoint.
        if was_suspended and run_id not in self._workers:
            if not entry.goal:
                # Metadata missing (corrupted / test stub) — honest failure.
                return await self._send_error(
                    writer, 409, "no_worker",
                    "run is suspended but has no usable metadata; cannot resume",
                )
            spawned = await self._spawn_suspended_resume(run_id, entry)
            if not spawned:
                # No loop_factory or components configured: cannot reconstruct worker.
                return await self._send_error(
                    writer, 409, "no_worker",
                    "run is suspended but this server has no loop_factory to resume it",
                )

        await self._send_json(writer, 202, {"state": "resume_requested"})

    async def _spawn_suspended_resume(self, run_id: str, entry) -> bool:
        """Reconstruct and start a RunWorker for a suspended run that has no live coroutine.

        Returns True if a worker was spawned, False if this server has no loop_factory
        or components (metadata-only mode) — caller maps False → 409 no_worker.

        Reads the last RunCheckpoint from the JSONL store so that:
          - _event_seq initialises from last_event_seq (SSE replay cursor not rewound)
          - _step_count initialises from last_step (step budget continues, not restart-from-0)
        """
        from argos.daemon.worker import RunWorker
        ckpt = self._manager.store.last_checkpoint(run_id)
        initial_event_seq = ckpt["last_event_seq"] if ckpt else entry.last_event_seq
        # ponytail: no checkpoint (lost/corrupt JSONL) → start at step 0; safe
        # (over-budget direction) but wastes steps already done.  Upgrade: write
        # a sentinel checkpoint on every state_change so this path is never hit.
        initial_step_count = ckpt["last_step"] if ckpt else 0
        effective_ws_str = entry.workspace or None
        effective_ws_path = (
            Path(effective_ws_str).expanduser().resolve()
            if effective_ws_str else None
        )
        if self._components is not None:
            from argos.app_factory import build_run_stack
            run_stack = build_run_stack(
                self._components,
                workspace=effective_ws_path,
                session_id=f"run-{run_id}",
            )
            worker = RunWorker(
                run_id=run_id,
                manager=self._manager,
                loop_factory=run_stack.loop_factory,
                registry=self._registry,
                worktree=self._worktree,
                gate=run_stack.gate,
                run_stack_close=run_stack.close,
                approval_timeout_s=60.0,
                ledger_store=self._ledger_store,
                initial_event_seq=initial_event_seq,
                initial_step_count=initial_step_count,
            )
        elif callable(self._loop_factory):
            run_loop_factory = self._make_run_loop_factory(effective_ws_str)
            worker = RunWorker(
                run_id=run_id,
                manager=self._manager,
                loop_factory=run_loop_factory,
                registry=self._registry,
                worktree=self._worktree,
                gate=self._gate,
                approval_timeout_s=60.0,
                ledger_store=self._ledger_store,
                initial_event_seq=initial_event_seq,
                initial_step_count=initial_step_count,
            )
        else:
            # Metadata-only server (no loop_factory / components): cannot spawn.
            return False
        # ponytail: the freshly-built AgentLoop runs its LoopConfig.max_steps from 0,
        # so a resumed run gets a full fresh step budget — not the remaining budget.
        # worker._step_count is seeded for checkpoint continuity only (SSE cursor +
        # honest step display).  Upgrade: thread remaining budget into LoopConfig.max_steps
        # if resume-budget-accuracy ever matters.
        self._spawn_worker(worker, run_id, name=f"resume-{run_id}")
        return True

    async def _handle_cancel(self, writer, headers, run_id):
        if (sid := await self._require_owner(writer, headers)) is None:
            return
        ok = await self._manager.request_cancel(run_id)
        if not ok:
            return await self._send_error(writer, 409, CODE_INVALID_TRANSITION,
                                          "run is in terminal state (cannot cancel)")
        worker = self._workers.get(run_id)
        if worker is not None:
            worker.request_hard_cancel()
        await self._send_json(writer, 202, {"state": "cancel_requested"})

    async def _handle_focus(self, writer, headers, run_id):
        """Internal documentation."""
        if (sid := await self._require_owner(writer, headers)) is None:
            return
        if self._registry.get(run_id) is None:
            return await self._send_error(writer, 404, CODE_NOT_FOUND, "run not found")
        self._registry.set_focus(run_id=run_id, session_id=sid)
        await self._send_json(writer, 200, {
            "run_id": run_id,
            "focus_session_id": sid,
        })

    async def _handle_approval(self, writer, headers, run_id, call_id, body):
        """Internal documentation."""
        if (sid := await self._require_owner(writer, headers)) is None:
            return
        try:
            data = json.loads(body.decode("utf-8") or "{}")
        except json.JSONDecodeError:
            return await self._send_error(writer, 400, CODE_BAD_REQUEST, "invalid JSON body")

        decision = data.get("decision")
        valid_decisions = ("deny", "once", "session", "always")
        if decision not in valid_decisions:
            return await self._send_error(
                writer, 400, CODE_BAD_REQUEST,
                f"decision must be one of {valid_decisions}",
            )

        worker = self._workers.get(run_id)
        if worker is None:
            if self._manager.get_run(run_id) is None:
                return await self._send_error(writer, 404, CODE_NOT_FOUND,
                                              f"run {run_id!r} not found")
            return await self._send_error(writer, 404, CODE_NOT_FOUND,
                                          f"run {run_id!r} has no active worker "
                                          "(already completed or never started)")

        gate = worker.gate
        if gate is None:
            return await self._send_error(
                writer, 409, "no_approval_gate",
                f"run {run_id!r} has no approval gate (FakeLoop / no-gate path)",
            )

        from argos.daemon.worker import DaemonApprovalGate
        if isinstance(gate, DaemonApprovalGate) and not gate.has_pending_call(call_id):
            return await self._send_error(
                writer, 409, "unknown_call_id",
                f"call_id {call_id!r} is not pending in run {run_id!r} "
                "(already resolved, timed out, or wrong run)",
            )

        resolved = gate.respond(call_id, decision)
        if not resolved:
            return await self._send_error(
                writer, 409, "call_id_already_resolved",
                f"call_id {call_id!r} was already resolved (timeout race) in run {run_id!r}",
            )

        approval_ev = {
            "kind": "approval_response",
            "call_id": call_id,
            "decision": decision,
            "run_id": run_id,
            "ts": time.time(),
        }
        self._manager.store.append(run_id, approval_ev)
        await self._manager.fanout(run_id, approval_ev)

        await self._send_json(writer, 200, {
            "call_id": call_id,
            "decision": decision,
            "state": "applied",
        })

    async def _handle_plan_decision(self, writer, headers, run_id, body):
        """Internal documentation."""
        if (sid := await self._require_owner(writer, headers)) is None:
            return
        worker = self._workers.get(run_id)
        if worker is None:
            if self._manager.get_run(run_id) is None:
                return await self._send_error(
                    writer, 404, CODE_NOT_FOUND, f"run {run_id!r} not found",
                )
            return await self._send_error(
                writer, 404, CODE_NOT_FOUND,
                f"run {run_id!r} has no active worker (already completed or never started)",
            )

        try:
            payload = json.loads(body) if body else {}
        except Exception:
            return await self._send_error(writer, 400, CODE_BAD_REQUEST, "invalid JSON body")

        call_id = payload.get("call_id", "")
        action = payload.get("action", "")
        feedback = payload.get("feedback") or None

        if not call_id:
            return await self._send_error(writer, 400, CODE_BAD_REQUEST, "missing call_id")
        if not action:
            return await self._send_error(writer, 400, CODE_BAD_REQUEST, "missing action")

        loop = getattr(worker, "_loop", None) or getattr(worker, "loop", None)
        if loop is None or not hasattr(loop, "respond_plan_decision"):
            return await self._send_error(
                writer, 409, "loop_not_available",
                f"loop for run {run_id!r} is not available or not running",
            )

        if call_id not in getattr(loop, "_plan_call_registry", {}):
            return await self._send_error(
                writer, 409, "unknown_call_id",
                f"call_id {call_id!r} is not pending in run {run_id!r} "
                "(may have timed out or already resolved)",
            )

        ok = loop.respond_plan_decision(call_id, action, feedback)
        if not ok:
            current_mode = getattr(loop, "mode", "act")
            if current_mode != "plan":
                return await self._send_error(
                    writer, 409, CODE_INVALID_TRANSITION,
                    f"plan_decision rejected: loop is no longer in plan mode "
                    f"(current mode: {current_mode!r}; already resolved or raced)",
                )
            return await self._send_error(
                writer, 400, CODE_BAD_REQUEST,
                f"plan_decision rejected: invalid action {action!r} or missing feedback for refine",
            )

        plan_ev = {
            "kind": "plan_decision_response",
            "call_id": call_id,
            "action": action,
            "run_id": run_id,
            "ts": time.time(),
        }
        self._manager.store.append(run_id, plan_ev)
        await self._manager.fanout(run_id, plan_ev)

        await self._send_json(writer, 200, {
            "call_id": call_id,
            "action": action,
            "state": "applied",
        })

    # ── P3b Ledger endpoints ─────────────────────────────────────────

    async def _handle_get_ledger(self, writer, headers, run_id):
        """Internal documentation."""
        if await self._require_session(writer, headers) is None:
            return
        if self._manager.get_run(run_id) is None:
            return await self._send_error(writer, 404, CODE_NOT_FOUND, "run not found")

        ledger_store = getattr(self, "_ledger_store", None)
        if ledger_store is None:
            return await self._send_json(writer, 200, {"run_id": run_id, "entries": []})

        try:
            entries = ledger_store.replay(run_id)
            await self._send_json(writer, 200, {
                "run_id": run_id,
                "entries": [e.to_dict() for e in entries],
            })
        except Exception as e:  # noqa: BLE001
            log.exception("ledger replay error for %s: %s", run_id, e)
            await self._send_error(writer, 500, CODE_INTERNAL, str(e))

    async def _handle_undo(self, writer, headers, run_id, body):
        """Internal documentation."""
        if await self._require_owner(writer, headers) is None:
            return

        if self._manager.get_run(run_id) is None:
            return await self._send_error(writer, 404, CODE_NOT_FOUND, "run not found")

        ledger_store = getattr(self, "_ledger_store", None)
        if ledger_store is None:
            return await self._send_error(
                writer, 409, "nothing_to_undo",
                t("daemon.srv.undo_no_ledger"),
            )

        try:
            body_data = json.loads(body.decode("utf-8") or "{}") if body else {}
        except json.JSONDecodeError:
            body_data = {}
        entry_seq: int | None = body_data.get("entry_seq")
        if entry_seq is not None:
            try:
                entry_seq = int(entry_seq)
            except (ValueError, TypeError):
                return await self._send_error(
                    writer, 400, CODE_BAD_REQUEST,
                    t("daemon.srv.undo_entry_seq_must_be_int"),
                )

        if entry_seq is not None:
            return await self._handle_undo_entry(writer, run_id, ledger_store, entry_seq)


        if ledger_store.is_undo_done(run_id):
            return await self._send_error(
                writer, 409, "already_undone",
                t("daemon.srv.undo_already_done"),
            )

        entries = ledger_store.replay(run_id)
        available = [e for e in entries if e.undo_state == "available"]
        if not available:
            return await self._send_error(
                writer, 409, "nothing_to_undo",
                t("daemon.srv.undo_nothing_available"),
            )

        undo_token: str | None = None
        for e in available:
            if e.undo_token and not e.undo_token.startswith("file:"):
                undo_token = e.undo_token
                break

        if not undo_token:
            try:
                from argos.core.snapshot import SNAPSHOT_ROOT as _SNAP_ROOT
                _snap_candidate = _SNAP_ROOT / f"run-{run_id}.tar"
                if _snap_candidate.exists():
                    undo_token = str(_snap_candidate)
            except Exception:  # noqa: BLE001
                pass

        if not undo_token:
            return await self._send_error(
                writer, 409, "no_snapshot",
                t("daemon.srv.undo_no_snapshot"),
            )

        from pathlib import Path as _Path
        snap_path = _Path(undo_token)
        if not snap_path.exists():
            return await self._send_error(
                writer, 409, "no_snapshot",
                t("daemon.srv.undo_snap_missing", snap_path=snap_path),
            )

        run_meta = self._manager.get_run(run_id)
        workspace_str = getattr(run_meta, "workspace", "") or ""
        if not workspace_str:
            return await self._send_error(
                writer, 409, "no_workspace",
                t("daemon.srv.undo_no_workspace_run"),
            )

        workspace = _Path(workspace_str).expanduser().resolve()
        if not workspace.exists():
            return await self._send_error(
                writer, 409, "no_workspace",
                t("daemon.srv.undo_workspace_missing", workspace=workspace),
            )

        from argos.core.snapshot import RunSnapshot
        snapshot = RunSnapshot(tar_path=snap_path)
        result = snapshot.restore(workspace)

        if result.errors:
            ledger_store.undo_complete(run_id)
            error_detail = "; ".join(f"{p}: {e}" for p, e in result.errors[:3])
            return await self._send_json(writer, 200, {
                "run_id": run_id,
                "state": "partial",
                "restored": len(result.restored),
                "errors": len(result.errors),
                "error_detail": error_detail,
                "note": t("daemon.srv.undo_partial_note"),
            })

        ledger_store.undo_complete(run_id)

        undo_ev = {
            "kind": "undo_done",
            "run_id": run_id,
            "restored": len(result.restored),
            "ts": time.time(),
        }
        self._manager.store.append(run_id, undo_ev)
        await self._manager.fanout(run_id, undo_ev)

        await self._send_json(writer, 200, {
            "run_id": run_id,
            "state": "done",
            "restored": len(result.restored),
            "note": t("daemon.srv.undo_done_note"),
        })

    async def _handle_undo_entry(self, writer, run_id: str, ledger_store, entry_seq: int):
        """Internal documentation."""
        from pathlib import Path as _Path
        from argos.core.snapshot import RunSnapshot

        ledger_entry = ledger_store.get_entry(run_id, entry_seq)
        if ledger_entry is None:
            return await self._send_error(
                writer, 409, "entry_not_found",
                t("daemon.srv.undo_entry_not_found", entry_seq=entry_seq),
            )

        if not ledger_entry.undo_token or not ledger_entry.undo_token.startswith("file:"):
            return await self._send_error(
                writer, 409, "not_file_entry",
                t("daemon.srv.undo_entry_not_file", entry_seq=entry_seq),
            )

        if ledger_entry.reversible != "yes":
            return await self._send_error(
                writer, 409, "not_reversible",
                t("daemon.srv.undo_entry_not_reversible",
                  entry_seq=entry_seq, reversible=ledger_entry.reversible),
            )

        if ledger_entry.undo_state == "done":
            return await self._send_error(
                writer, 409, "already_undone",
                t("daemon.srv.undo_entry_already_done", entry_seq=entry_seq),
            )

        file_path_str = ledger_entry.undo_token[len("file:"):]

        all_entries = ledger_store.replay(run_id)
        snap_token: str | None = None
        for e in all_entries:
            if e.undo_token and not e.undo_token.startswith("file:") and e.undo_state == "available":
                snap_token = e.undo_token
                break
        if snap_token is None:
            for e in all_entries:
                if e.undo_token and not e.undo_token.startswith("file:"):
                    snap_token = e.undo_token
                    break

        if not snap_token:
            return await self._send_error(
                writer, 409, "no_snapshot",
                t("daemon.srv.undo_entry_no_snapshot"),
            )

        snap_path = _Path(snap_token)
        if not snap_path.exists():
            return await self._send_error(
                writer, 409, "no_snapshot",
                t("daemon.srv.undo_entry_snap_missing", snap_path=snap_path),
            )

        run_meta = self._manager.get_run(run_id)
        workspace_str = getattr(run_meta, "workspace", "") or ""
        if not workspace_str:
            return await self._send_error(
                writer, 409, "no_workspace",
                t("daemon.srv.undo_entry_no_workspace"),
            )
        workspace = _Path(workspace_str).expanduser().resolve()
        if not workspace.exists():
            return await self._send_error(
                writer, 409, "no_workspace",
                t("daemon.srv.undo_entry_workspace_missing", workspace=workspace),
            )

        try:
            file_abs = _Path(file_path_str).resolve()
            rel_path = str(file_abs.relative_to(workspace))
        except (ValueError, OSError):
            rel_path = file_path_str.lstrip("/")

        snapshot = RunSnapshot(tar_path=snap_path)
        result = snapshot.restore_file(workspace, rel_path)

        if result.errors:
            error_detail = "; ".join(f"{p}: {e}" for p, e in result.errors[:3])
            return await self._send_error(
                writer, 500, "restore_failed",
                t("daemon.srv.undo_entry_restore_failed", error_detail=error_detail),
            )

        ledger_store.mark_entry_done(run_id, entry_seq)

        was_new_file = bool(result.missing)
        if was_new_file:
            note = t("daemon.srv.undo_entry_new_file_note", file_path=file_path_str)
        else:
            note = t("daemon.srv.undo_entry_restored_note", file_path=file_path_str)

        undo_ev = {
            "kind": "undo_entry_done",
            "run_id": run_id,
            "entry_seq": entry_seq,
            "file_path": file_path_str,
            "was_new_file": was_new_file,
            "ts": time.time(),
        }
        self._manager.store.append(run_id, undo_ev)
        await self._manager.fanout(run_id, undo_ev)

        await self._send_json(writer, 200, {
            "run_id": run_id,
            "entry_seq": entry_seq,
            "state": "done",
            "file_path": file_path_str,
            "was_new_file": was_new_file,
            "note": note,
        })


    def _conductor_orders_dir(self):
        """Internal documentation."""
        if self._conductor is not None:
            return self._conductor._orders_dir
        from argos.daemon.__main__ import _default_conductor_dir
        return _default_conductor_dir()

    async def _handle_create_order(self, writer, headers, body):
        """Internal documentation."""
        if await self._require_owner(writer, headers) is None:
            return
        try:
            data = json.loads(body.decode("utf-8") or "{}")
        except json.JSONDecodeError:
            return await self._send_error(writer, 400, CODE_BAD_REQUEST, "invalid JSON body")

        utterance = data.get("utterance", "").strip()
        kind = data.get("kind", "")
        goal_template = data.get("goal_template", "").strip()
        if not utterance:
            return await self._send_error(writer, 400, CODE_BAD_REQUEST, "missing utterance")
        if kind not in ("schedule", "file_trigger"):
            return await self._send_error(writer, 400, CODE_BAD_REQUEST,
                                          "kind must be 'schedule' or 'file_trigger'")
        if not goal_template:
            return await self._send_error(writer, 400, CODE_BAD_REQUEST, "missing goal_template")
        if kind == "schedule" and not data.get("schedule"):
            return await self._send_error(writer, 400, CODE_BAD_REQUEST,
                                          "schedule required when kind=schedule")
        if kind == "file_trigger" and not data.get("trigger_glob"):
            return await self._send_error(writer, 400, CODE_BAD_REQUEST,
                                          "trigger_glob required when kind=file_trigger")

        from argos.conductor.orders import StandingOrder, OrderStore
        import uuid as _uuid
        order = StandingOrder(
            id=_uuid.uuid4().hex,
            utterance=utterance,
            kind=kind,
            schedule=data.get("schedule") or None,
            trigger_glob=data.get("trigger_glob") or None,
            goal_template=goal_template,
            enabled=bool(data.get("enabled", True)),
            created_at=time.time(),
            last_fired_at=None,
        )
        store = OrderStore(self._conductor_orders_dir())
        store.add(order)
        await self._send_json(writer, 201, order.to_dict())

    async def _handle_list_orders(self, writer, headers):
        """Internal documentation."""
        if await self._require_session(writer, headers) is None:
            return
        from argos.conductor.orders import OrderStore
        store = OrderStore(self._conductor_orders_dir())
        orders = store.list()
        await self._send_json(writer, 200, [o.to_dict() for o in orders])

    async def _handle_delete_order(self, writer, headers, order_id):
        """Internal documentation."""
        if await self._require_owner(writer, headers) is None:
            return
        if not order_id:
            return await self._send_error(writer, 400, CODE_BAD_REQUEST, "missing order id")
        from argos.conductor.orders import OrderStore
        store = OrderStore(self._conductor_orders_dir())
        deleted = store.delete(order_id)
        if not deleted:
            return await self._send_error(writer, 404, CODE_NOT_FOUND,
                                          f"order {order_id!r} not found")
        await self._send_json(writer, 204, {"ok": True})


    async def _handle_list_suggestions(self, writer, headers):
        """Internal documentation."""
        if await self._require_session(writer, headers) is None:
            return
        if self._conductor is None:
            return await self._send_json(writer, 200, [])
        pending = self._conductor.pending_suggestions
        result = [
            {
                "suggestion_id": s.id,
                "order_id": s.order_id,
                "goal": s.goal,
                "reason_human": s.reason_human,
                "suggested_at": s.suggested_at,
                "requires_confirmation": s.requires_confirmation,
            }
            for s in pending.values()
        ]
        await self._send_json(writer, 200, result)

    async def _handle_confirm_suggestion(self, writer, headers, suggestion_id):
        """Internal documentation."""
        if await self._require_owner(writer, headers) is None:
            return
        if not suggestion_id:
            return await self._send_error(writer, 400, CODE_BAD_REQUEST, "missing suggestion id")
        if self._conductor is None:
            return await self._send_error(writer, 503, "conductor_unavailable",
                                          t("daemon.srv.conductor_unavailable_confirm"))

        s = self._conductor.get_suggestion(suggestion_id)
        if s is None:
            return await self._send_error(writer, 404, CODE_NOT_FOUND,
                                          f"suggestion {suggestion_id!r} not found or already dismissed")
        if getattr(s, "action", "run") == "dream":
            return await self._confirm_dream(writer, suggestion_id, s)

        if self._loop_factory is _NO_KEY:
            return await self._send_error(
                writer, 503, "no_worker_key",
                t("daemon.srv.no_key_run_confirm"),
            )

        if not self._registry.has_capacity():
            return await self._send_error(
                writer, 503, CODE_BUSY,
                t("daemon.srv.busy_suggestion_capacity",
                  max_concurrent=self._registry.max_concurrent,
                  active_count=self._registry.active_count),
            )
        try:
            await asyncio.wait_for(self._registry.acquire_slot(), timeout=0.01)
        except asyncio.TimeoutError:
            return await self._send_error(
                writer, 503, CODE_BUSY,
                t("daemon.srv.busy_suggestion_timeout",
                  max_concurrent=self._registry.max_concurrent),
            )

        try:
            run_id = await self._manager.create_run(
                goal=s.goal,
                workspace="",
                model="",
                approval_level="confirm",
            )
        except Exception:
            self._registry.release_slot()
            raise

        wt_path = None
        try:
            wt_path = self._worktree.create(run_id=run_id, workspace="")
        except Exception as e:  # noqa: BLE001
            log.warning("conductor confirm: worktree 创建失败(fallback 无 worktree): %s", e)

        await self._registry.register(
            run_id=run_id, goal=s.goal, workspace="", worktree_path=wt_path,
        )

        from argos.daemon.worker import RunWorker

        if self._components is not None:
            from argos.app_factory import build_run_stack
            from pathlib import Path as _Path
            effective_ws_path = _Path(wt_path).expanduser().resolve() if wt_path else None
            run_stack = build_run_stack(
                self._components,
                workspace=effective_ws_path,
                session_id=f"run-{run_id}",
            )
            try:
                from argos.permissions.trust_dial import TrustLevel
                run_stack.gate.set_trust_level(TrustLevel["L1_DANGEROUS_ONLY"])
            except Exception as _te:  # noqa: BLE001
                log.warning("conductor confirm: set_trust_level 失败(诚实降级): %s", _te)

            worker = RunWorker(
                run_id=run_id,
                manager=self._manager,
                loop_factory=run_stack.loop_factory,
                registry=self._registry,
                worktree=self._worktree,
                gate=run_stack.gate,
                run_stack_close=run_stack.close,
                approval_timeout_s=60.0,
                ledger_store=self._ledger_store,
            )
            self._spawn_worker(worker, run_id, name=f"conductor-run-{run_id}")
        elif callable(self._loop_factory):
            worker = RunWorker(
                run_id=run_id,
                manager=self._manager,
                loop_factory=self._loop_factory,
                registry=self._registry,
                worktree=self._worktree,
                gate=self._gate,
                approval_timeout_s=60.0,
                ledger_store=self._ledger_store,
            )
            if self._gate is not None:
                try:
                    from argos.permissions.trust_dial import TrustLevel
                    self._gate.set_trust_level(TrustLevel["L1_DANGEROUS_ONLY"])
                except Exception as _te:  # noqa: BLE001
                    log.warning("conductor confirm: set_trust_level(shared gate) 失败: %s", _te)
            self._spawn_worker(worker, run_id, name=f"conductor-run-{run_id}")
        else:
            self._registry.release_slot()

        self._conductor.pop_suggestion(suggestion_id)

        confirm_ev = {
            "kind": "suggestion_confirmed",
            "suggestion_id": suggestion_id,
            "run_id": run_id,
            "worktree_path": wt_path,
            "trust_level": "L1_DANGEROUS_ONLY",
            "ts": time.time(),
        }
        self._manager.store.append(run_id, confirm_ev)
        await self._manager.fanout(run_id, confirm_ev)

        await self._send_json(writer, 201, {
            "run_id": run_id,
            "suggestion_id": suggestion_id,
            "isolation": "worktree",
            "trust_level": "L1_DANGEROUS_ONLY",
            "worktree_path": wt_path,
        })

    async def _handle_dismiss_suggestion(self, writer, headers, suggestion_id):
        """Internal documentation."""
        if await self._require_owner(writer, headers) is None:
            return
        if not suggestion_id:
            return await self._send_error(writer, 400, CODE_BAD_REQUEST, "missing suggestion id")
        if self._conductor is None:
            return await self._send_error(writer, 503, "conductor_unavailable",
                                          t("daemon.srv.conductor_unavailable_dismiss"))
        dismissed = self._conductor.dismiss_suggestion(suggestion_id)
        if not dismissed:
            return await self._send_error(writer, 404, CODE_NOT_FOUND,
                                          f"suggestion {suggestion_id!r} not found or already dismissed")
        await self._send_json(writer, 200, {"suggestion_id": suggestion_id, "state": "dismissed"})


    def _dreams_dir(self) -> Path:
        """Internal documentation."""
        import os
        override = os.environ.get("ARGOS_DREAMS_DIR")
        if override:
            return Path(override).expanduser()
        from argos.daemon.__main__ import _default_argos_dir
        return _default_argos_dir() / "dreams"

    def _get_dream_pipeline(self):
        """Internal documentation."""
        if self._dream_pipeline is not None:
            return self._dream_pipeline
        if self._components is None:
            return None
        client = getattr(self._components, "model", None)
        if client is None:
            return None

        from argos.app_factory import build_run_stack
        from argos.eval.runner import EvalRunner
        from argos.learning.dream import DreamPipeline, HintedRunner

        dreams_dir = self._dreams_dir()
        from argos.daemon.__main__ import _default_argos_dir
        argos_dir = _default_argos_dir()
        candidates_root = argos_dir / "learning" / "candidates"
        skills_root = argos_dir / "skills"
        memory_dir = argos_dir / "memory"
        eval_base = dreams_dir / "eval"

        run_stack = build_run_stack(
            self._components, workspace=None, session_id="dream-eval",
        )

        def _eval_loop_factory(model_tier: str):
            return run_stack.loop_factory()

        base_runner = EvalRunner(
            worktree=self._worktree,
            base_dir=eval_base,
            loop_factory=_eval_loop_factory,
        )

        def _runner_factory(hint):
            return HintedRunner(inner=base_runner, hint=hint) if hint else base_runner

        async def _narrate(prompt: str) -> str:
            return await asyncio.wait_for(
                client.complete(
                    [{"role": "user", "content": prompt}],
                    system=t("daemon.srv.dream_narrate_system"),
                ),
                timeout=60.0,
            )

        async def _dream_bcast(ev: dict) -> None:
            payload = {**ev, "run_id": CONDUCTOR_RUN_ID}
            await self._manager.fanout(CONDUCTOR_RUN_ID, payload)

        self._dream_pipeline = DreamPipeline(
            candidates_root=candidates_root,
            skills_root=skills_root,
            memory_dir=memory_dir,
            dreams_dir=dreams_dir,
            runner_factory=_runner_factory,
            narrate=_narrate,
            broadcast_fn=_dream_bcast,
        )
        return self._dream_pipeline

    async def _autonomous_dream_starter(self, s) -> bool:
        """Internal documentation."""
        pipeline = self._get_dream_pipeline()
        if pipeline is None:
            log.debug("conductor autonomous dream: 无 pipeline(no key)，本次跳过")
            return False
        if pipeline.is_running or self._dream_starting or pipeline.cross_process_busy():
            log.debug("conductor autonomous dream: pipeline busy，本次跳过")
            return False
        self._dream_starting = True

        def _reset_starting(_fut):
            self._dream_starting = False
            try:
                exc = _fut.exception() if not _fut.cancelled() else None
            except Exception:  # noqa: BLE001
                exc = None
            if exc is not None:
                log.warning("conductor autonomous dream-run 任务异常: %s", exc)

        task = asyncio.create_task(pipeline.run(), name="dream-run-autonomous")
        task.add_done_callback(_reset_starting)
        return True

    async def _start_dream(self, writer):
        """Internal documentation."""
        pipeline = self._get_dream_pipeline()
        if pipeline is None:
            await self._send_error(
                writer, 503, "no_worker_key",
                t("daemon.srv.no_key_dream"),
            )
            return False
        if pipeline.is_running or self._dream_starting or pipeline.cross_process_busy():
            await self._send_error(
                writer, 409, "dream_busy", t("daemon.srv.dream_busy"),
            )
            return False
        self._dream_starting = True

        def _reset_starting(_fut):
            self._dream_starting = False
            try:
                exc = _fut.exception() if not _fut.cancelled() else None
            except Exception:  # noqa: BLE001
                exc = None
            if exc is not None:
                log.warning("dream-run 任务异常退出: %s", exc)

        task = asyncio.create_task(pipeline.run(), name="dream-run")
        task.add_done_callback(_reset_starting)
        return True

    async def _confirm_dream(self, writer, suggestion_id, s):
        """Internal documentation."""
        started = await self._start_dream(writer)
        if not started:
            return
        self._conductor.pop_suggestion(suggestion_id)
        confirm_ev = {
            "kind": "suggestion_confirmed",
            "suggestion_id": suggestion_id,
            "run_id": CONDUCTOR_RUN_ID,
            "dream": True,
            "ts": time.time(),
        }
        await self._manager.fanout(CONDUCTOR_RUN_ID, confirm_ev)
        await self._send_json(writer, 202, {
            "state": "dream_started",
            "suggestion_id": suggestion_id,
        })

    async def _handle_dream_run(self, writer, headers):
        """Internal documentation."""
        if await self._require_owner(writer, headers) is None:
            return
        started = await self._start_dream(writer)
        if not started:
            return
        await self._send_json(writer, 202, {"state": "dream_started"})

    async def _handle_dream_report(self, writer, headers):
        """Internal documentation."""
        if await self._require_owner(writer, headers) is None:
            return
        report = self._read_latest_dream_report()
        await self._send_json(writer, 200, {"report": report})

    def _read_latest_dream_report(self) -> dict | None:
        """Internal documentation."""
        dreams_dir = self._dreams_dir()
        try:
            if not dreams_dir.exists():
                return None
            files = sorted(dreams_dir.glob("*.jsonl"))
            if not files:
                return None
            latest = files[-1]
            last_obj: dict | None = None
            for line in latest.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    last_obj = json.loads(line)
                except json.JSONDecodeError:
                    continue
            return last_obj
        except Exception as e:  # noqa: BLE001
            log.warning("dream report 读取失败(降级空态): %s", e)
            return None

    # ── SSE ──────────────────────────────────────────────────────────

    async def _handle_sse(self, writer, headers, run_id, query):
        if (sid := await self._require_session(writer, headers)) is None:
            return
        if not run_id.startswith("_") and not self._manager.get_run(run_id):
            return await self._send_error(writer, 404, CODE_NOT_FOUND, "run not found")
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
        if not run_id.startswith("_"):
            try:
                for ev in self._manager.store.replay(run_id, since_seq=since):
                    await self._send_sse_event(writer, ev)
            except Exception as e:  # noqa: BLE001
                log.warning("SSE replay error for %s: %s", run_id, e)
        q = self._manager.subscribe(run_id)
        try:
            if self._run_is_terminal(run_id):
                return
            while True:
                try:
                    ev = await asyncio.wait_for(q.get(), timeout=2.0)
                except asyncio.TimeoutError:
                    if self._run_is_terminal(run_id):
                        break
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
                if q.empty() and self._run_is_terminal(run_id):
                    break
        except (ConnectionResetError, BrokenPipeError, asyncio.CancelledError):
            pass
        finally:
            self._manager.unsubscribe(run_id, q)
            try:
                writer.close()
            except Exception:  # noqa: BLE001
                pass

    def _run_is_terminal(self, run_id: str) -> bool:
        """Internal documentation."""
        run = self._manager.get_run(run_id)
        return run is not None and run.state in TERMINAL_STATES

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
