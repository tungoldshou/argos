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
  POST /runs/{id}/plan_decision

注:#5a 单 TUI 限定 → 所有 session 都 write-capable(无 read-only 降级)。
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from argos_agent.app_factory import build_run_stack
from argos_agent.daemon.manager import RunManager
from argos_agent.daemon.protocol import (
    CODE_BAD_REQUEST, CODE_BUSY, CODE_INTERNAL, CODE_INVALID_TRANSITION,
    CODE_MISSING_SESSION, CODE_NOT_FOUND, CODE_SESSION_READONLY, HEADER_SESSION,
)
from argos_agent.daemon.sessions import SessionRegistry

log = logging.getLogger(__name__)


_HTTP_REASONS = {
    200: "OK", 201: "Created", 202: "Accepted", 204: "No Content",
    400: "Bad Request", 401: "Unauthorized", 404: "Not Found",
    409: "Conflict", 500: "Internal Server Error", 503: "Service Unavailable",
}


# 哨兵常量:__main__.py 在无 key 时传此值 → create_run 明确拒绝(诚实语义)。
# loop_factory=None(老测试路径/向后兼容)= 只创建元数据不 spawn worker,不拒绝。
_NO_KEY = object()


class DaemonHTTPServer:
    """Unix socket HTTP server,async。"""

    def __init__(self, *, manager: RunManager, socket_path: Path,
                 session_timeout_s: float = 30.0,
                 registry=None, worktree=None,
                 loop_factory=None, gate=None,
                 components=None):
        """loop_factory / components 二选一(components 优先走 per-run stack 路径)。

        None(默认) = 向后兼容:create_run 创建元数据但不 spawn worker(测试/无 loop 场景)。
        _NO_KEY 哨兵 = 无 key 诚实模式:create_run 明确拒绝并说明原因(不假装能跑)。
                      由 daemon/__main__.py 在装配失败时显式传入。
        callable   = 向后兼容:create_run 创建元数据 + spawn RunWorker(共享 sandbox/gate/broker)。
        components = AppComponents 实例:create_run 走 build_run_stack,每 run 独享一套
                     sandbox/gate/broker(并发不串台)。loop_factory 参数在此路径下被忽略。
        gate       = 向后兼容:仅当 loop_factory=callable(无 components)时有意义;
                     RunWorker 包 DaemonApprovalGate 实现 timeout fail-closed。
        """
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
        # per-run 栈路径:components 存在时优先(并发安全)
        self._components = components
        # 向后兼容:loop_factory 路径(共享 sandbox/gate/broker — 单 run 场景/测试)
        # components 存在时 loop_factory 忽略,但保留以不破坏老测试构造签名。
        self._loop_factory = loop_factory
        # 真 ApprovalGate(向后兼容 loop_factory 路径);components 路径下每 run 有自己的 gate。
        self._gate = gate
        self._server: asyncio.base_events.Server | None = None
        self._started_at: float = 0.0
        # P3 跨进程审批路由表:run_id → RunWorker
        # server 通过此表把 POST /runs/{id}/approval 路由到该 run 的 DaemonApprovalGate。
        self._workers: dict[str, "RunWorker"] = {}

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
                if method == "POST" and "/plan_decision" in rest:
                    rid = rest.split("/plan_decision")[0]
                    return await self._handle_plan_decision(writer, headers, rid, body)
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

    async def _require_owner(self, writer, headers) -> str | None:
        """#5b §7.2:owner 才放行写端点;observer / unknown → 403 session_readonly。"""
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
        # #5b §7.2 DELETE /sessions/{id} 也要 owner(防 observer 主动退出 hijack role);
        # 但 spec 同时允许 owner 退出触发 promote。最直觉:任何人能删自己 sid;上层调用
        # 用 sid 鉴权(不带 session header)。这里用 sid 直接鉴权,owner 退出自动 promote。
        new_owner = await self._sessions.promote_oldest_observer_after_remove(sid)
        await self._send_json(writer, 204, {"ok": True, "promoted_to": new_owner})

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
        if (sid := await self._require_owner(writer, headers)) is None:
            return
        try:
            data = json.loads(body.decode("utf-8") or "{}")
        except json.JSONDecodeError:
            return await self._send_error(writer, 400, CODE_BAD_REQUEST, "invalid JSON body")
        goal = data.get("goal")
        if not goal or not isinstance(goal, str):
            return await self._send_error(writer, 400, CODE_BAD_REQUEST, "missing goal")
        # P1 通电:无 key 诚实拒绝(在分配 slot/run 之前检查,不留垃圾元数据)
        # _NO_KEY 哨兵:daemon 启动时明确检测到无 key → 拒绝并说明原因
        if self._loop_factory is _NO_KEY:
            return await self._send_error(
                writer, 503, "no_worker_key",
                "daemon 未配置 API key,无法执行 run。"
                "请运行 `argos setup` 配置模型 key 后重启 daemon。",
            )

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

        # P1 通电:spawn RunWorker 协程
        # components 路径(优先):per-run 独享 sandbox/gate/broker — 并发安全
        # loop_factory 路径(向后兼容):共享组件,仅适合单 run 场景
        effective_ws_str = wt_path or (workspace if workspace else None)
        from argos_agent.daemon.worker import RunWorker
        # P3:approval_timeout_s 可由 create_run body 携带(默认 60s)。
        approval_timeout_s = float(data.get("approval_timeout_s", 60.0))
        if self._components is not None:
            # per-run 隔离栈:并发 run 各自独立 sandbox/gate/broker
            effective_ws_path = (
                Path(effective_ws_str).expanduser().resolve()
                if effective_ws_str else None
            )
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
                approval_timeout_s=approval_timeout_s,
            )
            # P3:注册 worker 到路由表,供审批路由使用
            self._workers[run_id] = worker
            asyncio.create_task(worker.run(), name=f"run-{run_id}")
        elif callable(self._loop_factory):
            # 向后兼容路径:共享 sandbox/gate/broker(loop_factory 注入)
            run_loop_factory = self._make_run_loop_factory(effective_ws_str)

            worker = RunWorker(
                run_id=run_id,
                manager=self._manager,
                loop_factory=run_loop_factory,
                registry=self._registry,
                worktree=self._worktree,
                gate=self._gate,
                approval_timeout_s=approval_timeout_s,
            )
            # P3:注册 worker 到路由表
            self._workers[run_id] = worker
            asyncio.create_task(worker.run(), name=f"run-{run_id}")

        await self._send_json(writer, 201, {"run_id": run_id})

    def _make_run_loop_factory(self, workspace: str | None):
        """返回 per-run loop_factory:在 base loop_factory 基础上用指定 workspace 覆盖。

        base loop_factory 已通过 app_factory.build_loop_factory() 装配好所有共享组件;
        per-run workspace 参数化让多 run 并发不共享 workspace 状态。
        """
        from pathlib import Path

        base_factory = self._loop_factory

        if not workspace:
            # 无指定 workspace:直接用 base factory(workspace 用 AppComponents 默认值)
            return base_factory

        ws_path = Path(workspace).expanduser().resolve()
        ws_path.mkdir(parents=True, exist_ok=True)

        def _run_specific_factory():
            loop = base_factory()
            # 覆盖 per-run workspace(AgentLoop._workspace / _verify_dir 是实例属性)
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
        if (sid := await self._require_owner(writer, headers)) is None:
            return
        ok = await self._manager.request_pause(run_id)
        if not ok:
            return await self._send_error(writer, 409, CODE_INVALID_TRANSITION,
                                          "run is not running (cannot pause)")
        await self._send_json(writer, 202, {"state": "pause_requested"})

    async def _handle_resume(self, writer, headers, run_id):
        if (sid := await self._require_owner(writer, headers)) is None:
            return
        ok = await self._manager.request_resume(run_id)
        if not ok:
            return await self._send_error(writer, 409, CODE_INVALID_TRANSITION,
                                          "run is not paused/suspended (cannot resume)")
        await self._send_json(writer, 202, {"state": "resume_requested"})

    async def _handle_cancel(self, writer, headers, run_id):
        if (sid := await self._require_owner(writer, headers)) is None:
            return
        ok = await self._manager.request_cancel(run_id)
        if not ok:
            return await self._send_error(writer, 409, CODE_INVALID_TRANSITION,
                                          "run is in terminal state (cannot cancel)")
        await self._send_json(writer, 202, {"state": "cancel_requested"})

    async def _handle_focus(self, writer, headers, run_id):
        """#5b POST /runs/{id}/focus:TUI 告诉 daemon "此 run 是我的 active 焦点"。

        owner-only(spec §7.2 权限矩阵)。"""
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
        """P3 跨进程审批响应入口。

        decision 接受 DecisionKind: deny|once|session|always。
        路由语义:
          1. 查路由表找 run_id 对应的 RunWorker。
          2. 通过 worker.gate.respond(call_id, decision) 立即 resolve 挂起的 Future。
          3. fanout approval_response 事件到 SSE(审计可见性:多客户端同步看到谁批了什么)。

        错误语义(fail-closed):
          · run_id 未知 → 404
          · call_id 不在该 run gate 的 pending 集合 → 409
          · decision 不合法 → 400
          · 任何路径都不自动放行
        """
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

        # 查路由表
        worker = self._workers.get(run_id)
        if worker is None:
            # run 存在但不在 worker 表(已结束/无法跑):特殊 404
            if self._manager.get_run(run_id) is None:
                return await self._send_error(writer, 404, CODE_NOT_FOUND,
                                              f"run {run_id!r} not found")
            return await self._send_error(writer, 404, CODE_NOT_FOUND,
                                          f"run {run_id!r} has no active worker "
                                          "(already completed or never started)")

        # 路由到 gate
        gate = worker.gate
        if gate is None:
            return await self._send_error(
                writer, 409, "no_approval_gate",
                f"run {run_id!r} has no approval gate (FakeLoop / no-gate path)",
            )

        # call_id 必须在该 run gate 的 pending 集合中
        from argos_agent.daemon.worker import DaemonApprovalGate
        if isinstance(gate, DaemonApprovalGate) and not gate.has_pending_call(call_id):
            return await self._send_error(
                writer, 409, "unknown_call_id",
                f"call_id {call_id!r} is not pending in run {run_id!r} "
                "(already resolved, timed out, or wrong run)",
            )

        # resolve 挂起 Future(立即唤醒 run)
        resolved = gate.respond(call_id, decision)
        if not resolved:
            # respond 返 False = pending 中途被清除(超时 race),诚实报 409
            return await self._send_error(
                writer, 409, "call_id_already_resolved",
                f"call_id {call_id!r} was already resolved (timeout race) in run {run_id!r}",
            )

        # fanout + 持久化 approval_response 事件(审计可见性 + 可回放)
        approval_ev = {
            "kind": "approval_response",
            "call_id": call_id,
            "decision": decision,
            "run_id": run_id,
            "ts": time.time(),
        }
        # 持久化到 JSONL store(供 replay 和审计)
        self._manager.store.append(run_id, approval_ev)
        # SSE 扇出(多客户端同步看到谁批了什么)
        await self._manager.fanout(run_id, approval_ev)

        await self._send_json(writer, 200, {
            "call_id": call_id,
            "decision": decision,
            "state": "applied",
        })

    async def _handle_plan_decision(self, writer, headers, run_id, body):
        """POST /runs/{id}/plan_decision — daemon 路径回传 plan 决策。

        v6 §4 ACP PlanDecisionRequest:与 /approval/{call_id} 同构,但服务 plan 决策
        而非工具审批。调用方提供 JSON body:
          {"call_id": "12hex", "action": "approve_start", "feedback": "..."}
        action 必须是 PlanExitDecision._VALID_ACTIONS 之一。

        fail-closed(铁律):
          · run 不存在 → 404
          · call_id 不在注册表(超时 race / 非法 id) → 409
          · action 非法 / refine 无 feedback → 400
          · respond_plan_decision 校验失败 → 400
          · 一切异常 → 500(不静默;让调用方知道)
        """
        # plan_decision 是等价于审批的控制变更(approve_start 会让 run 越过 plan 闸继续),
        # 与 approval/resume/cancel/focus 等控制端点一致,必须 owner-only。
        if (sid := await self._require_owner(writer, headers)) is None:
            return
        # 用 _workers 表找 RunWorker(而非 manager.get_run 的 RunEntry)
        worker = self._workers.get(run_id)
        if worker is None:
            # run 存在于 manager 但无 active worker(已完成/从未启动)
            if self._manager.get_run(run_id) is None:
                return await self._send_error(
                    writer, 404, CODE_NOT_FOUND, f"run {run_id!r} not found",
                )
            return await self._send_error(
                writer, 404, CODE_NOT_FOUND,
                f"run {run_id!r} has no active worker (already completed or never started)",
            )

        # 解析 body
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

        # 取 loop(per-run RunWorker 持有)
        loop = getattr(worker, "_loop", None) or getattr(worker, "loop", None)
        if loop is None or not hasattr(loop, "respond_plan_decision"):
            return await self._send_error(
                writer, 409, "loop_not_available",
                f"loop for run {run_id!r} is not available or not running",
            )

        # call_id 必须在 _plan_call_registry 中
        if call_id not in getattr(loop, "_plan_call_registry", {}):
            return await self._send_error(
                writer, 409, "unknown_call_id",
                f"call_id {call_id!r} is not pending in run {run_id!r} "
                "(may have timed out or already resolved)",
            )

        # 路由决策到 loop(等价于 ExitPlanMode;fail-closed 校验在 respond_plan_decision 内)。
        # respond_plan_decision 返回 False 有两类原因:
        #   a. 动作非法 / refine 无 feedback → 400(客户端输入错误)
        #   b. loop.mode 已翻回 act(本轮已解决/竞态) → 409(状态冲突,非输入错误)
        # 区分方式:直接调 ExitPlanMode 检查 loop.mode 来判断(respond_plan_decision 内已调)。
        ok = loop.respond_plan_decision(call_id, action, feedback)
        if not ok:
            # 检查是否竞态(loop 已退出 plan mode)
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

        # fanout plan_decision 事件(审计可见性)
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
