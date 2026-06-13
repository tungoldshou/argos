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

from argos.app_factory import build_run_stack
from argos.daemon.conductor_supervisor import CONDUCTOR_RUN_ID
from argos.daemon.manager import RunManager
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


# 哨兵常量:__main__.py 在无 key 时传此值 → create_run 明确拒绝(诚实语义)。
# loop_factory=None(老测试路径/向后兼容)= 只创建元数据不 spawn worker,不拒绝。
_NO_KEY = object()


class DaemonHTTPServer:
    """Unix socket HTTP server,async。"""

    def __init__(self, *, manager: RunManager, socket_path: Path,
                 session_timeout_s: float = 30.0,
                 registry=None, worktree=None,
                 loop_factory=None, gate=None,
                 components=None, ledger_store=None,
                 conductor_supervisor=None):
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
            from argos.daemon.registry import RunRegistry
            registry = RunRegistry()
        if worktree is None:
            from argos.daemon.worktree import WorktreeManager
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
        # P3b §6 行为账本存储(可选,None = 无账本功能)
        self._ledger_store = ledger_store
        # P5b §9 自治面:conductor supervisor(可选,None = 无自治功能)
        self._conductor = conductor_supervisor
        # Dream(T9):DreamPipeline 单例(懒初始化)。关键:单飞锁在**实例**上,每次
        # 新建 pipeline 锁就失效 —— 必须复用同一实例(_get_dream_pipeline 缓存)。
        # 无 components/model → _get_dream_pipeline 返 None(诚实无 key 模式)。
        self._dream_pipeline = None
        # TOCTOU 守卫:pipeline.is_running 只反映 run() 已持锁(锁在 create_task 派生
        # 的协程体内部惰性获取)。两个并发请求都可能在 run() 协程被调度前读到
        # is_running=False,各自 create_task 并返 202——违反"202=已启动"诚实铁律。
        # _dream_starting 在 is_running 检查通过后、create_task 之前同步置 True
        # (此处无 await,无法被抢占),done_callback 复位。
        self._dream_starting: bool = False

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
                if method == "POST" and "/intent_confirm" in rest:
                    rid = rest.split("/intent_confirm")[0]
                    return await self._handle_intent_confirm(writer, headers, rid, body)
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
            # P5b §9 自治面:Orders CRUD
            if method == "POST" and path == "/orders":
                return await self._handle_create_order(writer, headers, body)
            if method == "GET" and path == "/orders":
                return await self._handle_list_orders(writer, headers)
            if method == "DELETE" and path.startswith("/orders/"):
                order_id = path[len("/orders/"):]
                return await self._handle_delete_order(writer, headers, order_id)
            # P5b §9 自治面:Suggestions 确认 / 忽略
            if path.startswith("/suggestions/"):
                rest = path[len("/suggestions/"):]
                if method == "POST" and rest.endswith("/confirm"):
                    sid_part = rest[:-len("/confirm")]
                    return await self._handle_confirm_suggestion(writer, headers, sid_part)
                if method == "POST" and rest.endswith("/dismiss"):
                    sid_part = rest[:-len("/dismiss")]
                    return await self._handle_dismiss_suggestion(writer, headers, sid_part)
            # GET /suggestions（列出当前 pending）
            if method == "GET" and path == "/suggestions":
                return await self._handle_list_suggestions(writer, headers)
            # Dream(T9):手动触发 + 报告查询
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
        # 按需 reap(实测 bug 修复):reap_expired 此前零调用 = owner 永不过期、
        # observer 永不晋升 —— 重启 TUI 后新 session 永远 403 readonly。
        # 在鉴权前回收过期 session:过期 owner 让位 → promote 最旧 observer,
        # 本次请求即可以新身份通过 _require_owner(无需客户端重试)。
        try:
            await self._sessions.reap_expired()
        except Exception as _re:  # noqa: BLE001 — reap 失败不挡鉴权主路
            log.warning("session reap 失败(忽略): %s", _re)
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
        from argos.daemon.worker import RunWorker
        # P3:approval_timeout_s 可由 create_run body 携带(默认 60s)。
        approval_timeout_s = float(data.get("approval_timeout_s", 60.0))

        # P3b §6:run 起点快照(undo_token 来源)。
        # workspace 存在时拍快照;失败 fail-soft(snapshot=None → undo 诚实报 no_snapshot)。
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

        # P4 Trust Dial:per-run trust_level 参数(可选,默认沿用现有 approval_level 语义)。
        # trust_level 取枚举名字符串(如 "L1_DANGEROUS_ONLY")或 None(不传 → 不覆盖 approval_level)。
        # 传入时通过 gate.set_trust_level(TrustLevel[name]) 写入;枚举名非法 → 诚实降级(警告+忽略)。
        _trust_level_str = data.get("trust_level")

        def _apply_trust_to_gate(gate: "Any") -> None:
            """将 trust_level 字符串写入 gate;非法值静默降级(fail-safe)。

            components 路径:gate 由 build_run_stack 构造,reversible_lookup 已由
            app_factory 从 CapabilityRegistry 注入;此处只需写 trust_level。
            legacy loop_factory 路径:共享 gate 无 reversible_lookup 注入,L2 时
            evaluator 退化保守 ask(fail-closed 方向)。
            """
            if not _trust_level_str:
                return
            try:
                from argos.permissions.trust_dial import TrustLevel
                tl = TrustLevel[_trust_level_str]  # KeyError = 枚举名非法
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
            )
            # P3:注册 worker 到路由表,供审批路由使用
            self._workers[run_id] = worker
            asyncio.create_task(worker.run(), name=f"run-{run_id}")
        elif callable(self._loop_factory):
            # 向后兼容路径:共享 sandbox/gate/broker(loop_factory 注入)
            run_loop_factory = self._make_run_loop_factory(effective_ws_str)
            # 向后兼容路径的 gate 是全局共享 gate;trust_level 写入全局 gate(告警)
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
            )
            # P3:注册 worker 到路由表
            self._workers[run_id] = worker
            asyncio.create_task(worker.run(), name=f"run-{run_id}")
        else:
            # 元数据模式(components/loop_factory 均无):没有 worker 跑终态清理,
            # 槽位必须当场归还,否则 max_concurrent 次后 daemon 永久 503(槽位泄漏)。
            self._registry.release_slot()

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
        from argos.daemon.worker import DaemonApprovalGate
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

    async def _handle_intent_confirm(self, writer, headers, run_id, body):
        """POST /runs/{id}/intent_confirm — P4 §7 daemon 路径回传意图确认决策。

        与 /plan_decision 同构:
          body: {"call_id": "12hex", "confirmed": true, "revised_goal": null}
          confirmed=true  → loop 继续(使用 card.goal 或 revised_goal)
          confirmed=false → loop 诚实取消(fail-closed)

        fail-closed(铁律):
          · run/worker 不存在 → 404
          · call_id 不在注册表 → 409
          · body 缺 confirmed 字段 → 400
          · respond_intent_confirm 路由失败 → 409
        """
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
        if not call_id:
            return await self._send_error(writer, 400, CODE_BAD_REQUEST, "missing call_id")
        if "confirmed" not in payload:
            return await self._send_error(writer, 400, CODE_BAD_REQUEST, "missing confirmed field")
        confirmed = bool(payload["confirmed"])
        revised_goal = payload.get("revised_goal") or None

        # 取 loop
        loop = getattr(worker, "_loop", None) or getattr(worker, "loop", None)
        if loop is None or not hasattr(loop, "respond_intent_confirm"):
            return await self._send_error(
                writer, 409, "loop_not_available",
                f"loop for run {run_id!r} is not available or not running",
            )

        # call_id 必须在 _intent_confirm_registry 中
        if call_id not in getattr(loop, "_intent_confirm_registry", {}):
            return await self._send_error(
                writer, 409, "unknown_call_id",
                f"call_id {call_id!r} is not pending in run {run_id!r} "
                "(may have timed out or already resolved)",
            )

        ok = loop.respond_intent_confirm(call_id, confirmed, revised_goal)
        if not ok:
            return await self._send_error(
                writer, 409, "intent_confirm_failed",
                f"respond_intent_confirm failed for call_id {call_id!r} in run {run_id!r}",
            )

        # fanout intent_confirm 事件(审计可见性)
        ic_ev = {
            "kind": "intent_confirm_response",
            "call_id": call_id,
            "confirmed": confirmed,
            "revised_goal": revised_goal,
            "run_id": run_id,
            "ts": time.time(),
        }
        self._manager.store.append(run_id, ic_ev)
        await self._manager.fanout(run_id, ic_ev)

        await self._send_json(writer, 200, {
            "call_id": call_id,
            "confirmed": confirmed,
            "state": "applied",
        })

    # ── P3b Ledger endpoints ─────────────────────────────────────────

    async def _handle_get_ledger(self, writer, headers, run_id):
        """GET /runs/{id}/ledger — 回放账本(人话条目列表)。

        权限:session(只读观察者也能看账本)。
        返回:{"run_id": ..., "entries": [{...LedgerEntry.to_dict()...}, ...]}
        """
        if await self._require_session(writer, headers) is None:
            return
        if self._manager.get_run(run_id) is None:
            return await self._send_error(writer, 404, CODE_NOT_FOUND, "run not found")

        ledger_store = getattr(self, "_ledger_store", None)
        if ledger_store is None:
            # 无账本存储:返空列表(向后兼容,无账本不报错)
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
        """POST /runs/{id}/undo — run 级还原(快照还原 + 账本标记)。

        A3 扩展:body 可携带 entry_seq 字段 → 文件粒度还原(单条账本条目对应的文件)。
        无 entry_seq → 既有 run 级行为不变(整个 run 快照还原)。

        语义(诚实四分):
          · run 不存在                               → 404
          · 无账本                                   → 409 "nothing_to_undo"
          · entry_seq 指定:
            - 条目不存在                             → 409 "entry_not_found"
            - undo_token 不是 "file:" 前缀(非文件条目)→ 409 "not_file_entry"
            - reversible != yes                      → 409 "not_reversible"
            - undo_state 已为 done                   → 409 "already_undone"
            - 无快照 / 快照不存在                    → 409 "no_snapshot"
            - 还原成功                               → 200
          · 无 entry_seq(run 级):
            - 账本已有 undo_done 标记                → 409 "already_undone"
            - 无 reversible=yes 条目                 → 409 "nothing_to_undo"
            - 无快照 / 快照不存在                    → 409 "no_snapshot"
            - 还原成功                               → 200
          · 不可逆动作的条目不受影响(诚实)

        权限:owner-only(_require_owner 鉴权;交互审批门未接,与 run 级既有语义一致)。
        """
        if await self._require_owner(writer, headers) is None:
            return

        if self._manager.get_run(run_id) is None:
            return await self._send_error(writer, 404, CODE_NOT_FOUND, "run not found")

        ledger_store = getattr(self, "_ledger_store", None)
        if ledger_store is None:
            return await self._send_error(
                writer, 409, "nothing_to_undo",
                "此 run 无行为账本(ledger 未启用或 run 无副作用动作)",
            )

        # 解析 body(entry_seq 可选)
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
                    "entry_seq 必须为整数",
                )

        # ── A3 分支:文件粒度还原 ─────────────────────────────────────────
        if entry_seq is not None:
            return await self._handle_undo_entry(writer, run_id, ledger_store, entry_seq)

        # ── 既有 run 级还原路径(无 entry_seq)────────────────────────────

        # 已撤销检查
        if ledger_store.is_undo_done(run_id):
            return await self._send_error(
                writer, 409, "already_undone",
                "此 run 已执行过 undo,不可重复撤销",
            )

        # 有无 reversible=yes 条目
        entries = ledger_store.replay(run_id)
        available = [e for e in entries if e.undo_state == "available"]
        if not available:
            return await self._send_error(
                writer, 409, "nothing_to_undo",
                "此 run 无可撤销的操作(所有操作均不可逆或已无效)",
            )

        # 找 undo_token(run 级快照路径:不含 "file:" 前缀的条目)
        undo_token: str | None = None
        for e in available:
            if e.undo_token and not e.undo_token.startswith("file:"):
                undo_token = e.undo_token
                break

        # Minor-1 修正:纯文件编辑 run 账本条目全是 "file:" 前缀,扫不到非 file: 的 token。
        # fallback:按约定路径 SNAPSHOT_ROOT/run-{run_id}.tar 探测快照文件是否存在。
        if not undo_token:
            try:
                from argos.core.snapshot import SNAPSHOT_ROOT as _SNAP_ROOT
                _snap_candidate = _SNAP_ROOT / f"run-{run_id}.tar"
                if _snap_candidate.exists():
                    undo_token = str(_snap_candidate)
            except Exception:  # noqa: BLE001 — 兜底探测失败不崩，继续走 no_snapshot 路径
                pass

        if not undo_token:
            return await self._send_error(
                writer, 409, "no_snapshot",
                "无可用快照(run 起点快照不存在或路径丢失),无法执行文件系统还原",
            )

        from pathlib import Path as _Path
        snap_path = _Path(undo_token)
        if not snap_path.exists():
            return await self._send_error(
                writer, 409, "no_snapshot",
                f"快照文件不存在:{snap_path}",
            )

        # 找 workspace(从 run meta 拿)
        run_meta = self._manager.get_run(run_id)
        workspace_str = getattr(run_meta, "workspace", "") or ""
        if not workspace_str:
            return await self._send_error(
                writer, 409, "no_workspace",
                "run 无 workspace 路径,无法执行文件系统还原",
            )

        workspace = _Path(workspace_str).expanduser().resolve()
        if not workspace.exists():
            return await self._send_error(
                writer, 409, "no_workspace",
                f"workspace 不存在:{workspace}",
            )

        # 执行快照还原
        from argos.core.snapshot import RunSnapshot
        snapshot = RunSnapshot(tar_path=snap_path)
        result = snapshot.restore(workspace)

        if result.errors:
            # 部分失败:标记账本 + 诚实报告(不假装全成功)
            ledger_store.undo_complete(run_id)
            error_detail = "; ".join(f"{p}: {e}" for p, e in result.errors[:3])
            return await self._send_json(writer, 200, {
                "run_id": run_id,
                "state": "partial",
                "restored": len(result.restored),
                "errors": len(result.errors),
                "error_detail": error_detail,
                "note": "部分还原:快照已应用,但部分文件还原失败(见 error_detail)。账本已标记。",
            })

        # 全量成功
        ledger_store.undo_complete(run_id)

        # 广播 undo_done 事件(审计可见性)
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
            "note": "已还原 run 起点的文件改动(注:撤销还原整个 run 的文件改动,粒度为 run 级)。",
        })

    async def _handle_undo_entry(self, writer, run_id: str, ledger_store, entry_seq: int):
        """A3:文件粒度 undo — 按 entry_seq 还原单个文件。

        诚实四分(409 语义):
          · 条目不存在                → 409 entry_not_found
          · undo_token 非 file: 前缀 → 409 not_file_entry
          · reversible != yes        → 409 not_reversible
          · undo_state 已 done       → 409 already_undone
          · 快照不可用               → 409 no_snapshot
          · 还原成功                 → 200(entry undo_state → done)

        新建文件 undo = 删除(人话文案明说)。
        undo 仍走审批面(调用方已经过 _require_owner)。
        """
        from pathlib import Path as _Path
        from argos.core.snapshot import RunSnapshot

        # 查条目
        ledger_entry = ledger_store.get_entry(run_id, entry_seq)
        if ledger_entry is None:
            return await self._send_error(
                writer, 409, "entry_not_found",
                f"账本中不存在 seq={entry_seq} 的条目",
            )

        # undo_token 必须是 file: 前缀(文件粒度条目)
        if not ledger_entry.undo_token or not ledger_entry.undo_token.startswith("file:"):
            return await self._send_error(
                writer, 409, "not_file_entry",
                f"seq={entry_seq} 的条目不是文件类条目(undo_token 无 file: 前缀)",
            )

        # reversible 检查
        if ledger_entry.reversible != "yes":
            return await self._send_error(
                writer, 409, "not_reversible",
                f"seq={entry_seq} 的条目不可逆(reversible={ledger_entry.reversible!r}),无法撤销",
            )

        # 已撤销检查
        if ledger_entry.undo_state == "done":
            return await self._send_error(
                writer, 409, "already_undone",
                f"seq={entry_seq} 的条目已经撤销(undo_state=done),不可重复撤销",
            )

        # 从 undo_token 提取文件路径("file:{abs_path}")
        file_path_str = ledger_entry.undo_token[len("file:"):]

        # 找 run 级 undo_token(快照路径:不带 file: 前缀的 available 条目)
        all_entries = ledger_store.replay(run_id)
        snap_token: str | None = None
        for e in all_entries:
            if e.undo_token and not e.undo_token.startswith("file:") and e.undo_state == "available":
                snap_token = e.undo_token
                break
        # 也查 done 条目里有无快照(run 级 undo 已完成但单文件 undo 仍需快照)
        if snap_token is None:
            for e in all_entries:
                if e.undo_token and not e.undo_token.startswith("file:"):
                    snap_token = e.undo_token
                    break

        if not snap_token:
            return await self._send_error(
                writer, 409, "no_snapshot",
                "无法找到 run 起点快照路径,无法执行文件粒度还原",
            )

        snap_path = _Path(snap_token)
        if not snap_path.exists():
            return await self._send_error(
                writer, 409, "no_snapshot",
                f"快照文件不存在:{snap_path}",
            )

        # 找 workspace
        run_meta = self._manager.get_run(run_id)
        workspace_str = getattr(run_meta, "workspace", "") or ""
        if not workspace_str:
            return await self._send_error(
                writer, 409, "no_workspace",
                "run 无 workspace 路径,无法执行文件粒度还原",
            )
        workspace = _Path(workspace_str).expanduser().resolve()
        if not workspace.exists():
            return await self._send_error(
                writer, 409, "no_workspace",
                f"workspace 不存在:{workspace}",
            )

        # 计算相对路径(文件路径相对于 workspace)
        try:
            file_abs = _Path(file_path_str).resolve()
            rel_path = str(file_abs.relative_to(workspace))
        except (ValueError, OSError):
            # 绝对路径不在 workspace 内或无效:尝试直接用 file_path_str 作相对路径
            rel_path = file_path_str.lstrip("/")

        # 执行单文件还原
        snapshot = RunSnapshot(tar_path=snap_path)
        result = snapshot.restore_file(workspace, rel_path)

        if result.errors:
            error_detail = "; ".join(f"{p}: {e}" for p, e in result.errors[:3])
            return await self._send_error(
                writer, 500, "restore_failed",
                f"文件还原失败:{error_detail}",
            )

        # 标记该条目 undo_state → done
        ledger_store.mark_entry_done(run_id, entry_seq)

        # 判断结果类型:missing = run 中新建(撤销=删除),restored = 已还原
        was_new_file = bool(result.missing)
        if was_new_file:
            note = f"此文件是任务中新建的,撤销即删除(已删除:{file_path_str})"
        else:
            note = f"已还原文件:{file_path_str}"

        # 广播 undo_entry_done 事件(审计可见性)
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

    # ── P5b §9 自治面：Orders CRUD ───────────────────────────────────

    def _conductor_orders_dir(self):
        """conductor OrderStore 目录（与 conductor_supervisor 一致）。"""
        from pathlib import Path
        if self._conductor is not None:
            return self._conductor._orders_dir
        return Path.home() / ".argos" / "conductor"

    async def _handle_create_order(self, writer, headers, body):
        """POST /orders — 创建 StandingOrder。

        body JSON 字段：
          utterance     必填：人话描述
          kind          必填："schedule" 或 "file_trigger"
          schedule      kind=schedule 时必填：cron-lite 表达式
          trigger_glob  kind=file_trigger 时必填：文件 glob
          goal_template 必填：goal 模板
          enabled       可选：bool，默认 True
        返回 201 {id: "..."}；非法 body → 400。
        """
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
        """GET /orders — 列出所有 StandingOrder。"""
        if await self._require_session(writer, headers) is None:
            return
        from argos.conductor.orders import OrderStore
        store = OrderStore(self._conductor_orders_dir())
        orders = store.list()
        await self._send_json(writer, 200, [o.to_dict() for o in orders])

    async def _handle_delete_order(self, writer, headers, order_id):
        """DELETE /orders/{id} — 删除 StandingOrder。"""
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

    # ── P5b §9 自治面：Suggestions ──────────────────────────────────

    async def _handle_list_suggestions(self, writer, headers):
        """GET /suggestions — 列出当前 pending 建议（内存）。"""
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
        """POST /suggestions/{id}/confirm — 用户确认 → create_run（worktree 隔离 + L1 信任）。

        安全铁律（不可降级）：
          · isolation = "worktree"（写死）
          · trust_level = "L1_DANGEROUS_ONLY"（写死，不读全局 TrustDial）
        返回 {run_id: "..."}；未知 id → 404；已 dismiss → 409。
        """
        if await self._require_owner(writer, headers) is None:
            return
        if not suggestion_id:
            return await self._send_error(writer, 400, CODE_BAD_REQUEST, "missing suggestion id")
        if self._conductor is None:
            return await self._send_error(writer, 503, "conductor_unavailable",
                                          "conductor 未启动，无法确认建议")

        s = self._conductor.get_suggestion(suggestion_id)
        if s is None:
            return await self._send_error(writer, 404, CODE_NOT_FOUND,
                                          f"suggestion {suggestion_id!r} not found or already dismissed")
        # Dream(T9):action=="dream" → 路由 DreamPipeline，而非 create_run（spec §5）。
        # 已通过 _require_owner 鉴权 + suggestion 存在性检查,直接交给 _confirm_dream。
        if getattr(s, "action", "run") == "dream":
            return await self._confirm_dream(writer, suggestion_id, s)

        # 检查 loop_factory 可用（_NO_KEY 哨兵 = 无 key）
        if self._loop_factory is _NO_KEY:
            return await self._send_error(
                writer, 503, "no_worker_key",
                "daemon 未配置 API key，无法执行 run。请运行 `argos setup` 配置模型 key 后重启 daemon。",
            )

        # 并发槽位检查
        if not self._registry.has_capacity():
            return await self._send_error(
                writer, 503, CODE_BUSY,
                f"max_concurrent_runs_reached (max={self._registry.max_concurrent}, "
                f"active={self._registry.active_count})；建议已登记，请稍后重试确认",
            )
        try:
            await asyncio.wait_for(self._registry.acquire_slot(), timeout=0.01)
        except asyncio.TimeoutError:
            return await self._send_error(
                writer, 503, CODE_BUSY,
                f"max_concurrent_runs_reached (max={self._registry.max_concurrent})；"
                f"建议已登记，请稍后重试确认",
            )

        # 铁律：isolation=worktree，trust_level=L1_DANGEROUS_ONLY
        try:
            run_id = await self._manager.create_run(
                goal=s.goal,
                workspace="",         # worktree 从 base_dir 隔离，不需要用户 workspace
                model="",
                approval_level="confirm",
            )
        except Exception:
            self._registry.release_slot()
            raise

        # 创建 worktree（即使无 workspace 也在 WorktreeManager.base_dir 建 temp 目录）
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
            # 写死 L1_DANGEROUS_ONLY（铁律：自治 run 最高 L1，不读全局 TrustDial）
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
            self._workers[run_id] = worker
            asyncio.create_task(worker.run(), name=f"conductor-run-{run_id}")
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
            self._workers[run_id] = worker
            asyncio.create_task(worker.run(), name=f"conductor-run-{run_id}")
        else:
            # 元数据模式:没有 worker 跑终态清理,槽位当场归还(终审 major:槽位泄漏)。
            self._registry.release_slot()

        # 从 pending 移除（已确认，不再是 pending）
        self._conductor.pop_suggestion(suggestion_id)

        # 广播 confirm 事件（审计可见性）
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
        """POST /suggestions/{id}/dismiss — 用户忽略建议。"""
        if await self._require_owner(writer, headers) is None:
            return
        if not suggestion_id:
            return await self._send_error(writer, 400, CODE_BAD_REQUEST, "missing suggestion id")
        if self._conductor is None:
            return await self._send_error(writer, 503, "conductor_unavailable",
                                          "conductor 未启动")
        dismissed = self._conductor.dismiss_suggestion(suggestion_id)
        if not dismissed:
            return await self._send_error(writer, 404, CODE_NOT_FOUND,
                                          f"suggestion {suggestion_id!r} not found or already dismissed")
        await self._send_json(writer, 200, {"suggestion_id": suggestion_id, "state": "dismissed"})

    # ── Dream(T9):夜间整合接线 ───────────────────────────────────────────

    def _dreams_dir(self) -> Path:
        """Dream 报告目录。默认 ~/.argos/dreams；ARGOS_DREAMS_DIR 可覆盖（测试注入用）。

        与 _get_dream_pipeline 装配的 dreams_dir 同口径；GET /dream/report 也读这里。
        """
        import os
        override = os.environ.get("ARGOS_DREAMS_DIR")
        if override:
            return Path(override)
        return Path(os.path.expanduser("~/.argos/dreams"))

    def _get_dream_pipeline(self):
        """懒初始化并缓存 DreamPipeline 单例（单飞锁在实例上，必须复用同一实例）。

        无 components / 无 model（_NO_KEY 等价语义）→ 返 None（诚实无 key 模式，
        caller 回 503 no_worker_key）。已注入 _dream_pipeline（测试 fake）→ 直接返。
        """
        if self._dream_pipeline is not None:
            return self._dream_pipeline
        # 无 components → 无法 build_run_stack / 拿 model → 诚实返 None
        if self._components is None:
            return None
        client = getattr(self._components, "model", None)
        if client is None:
            return None

        import os
        from argos.app_factory import build_run_stack
        from argos.eval.runner import EvalRunner
        from argos.learning.candidates import DEFAULT_ROOT
        from argos.learning.dream import DreamPipeline, HintedRunner

        dreams_dir = self._dreams_dir()
        skills_root = Path(os.path.expanduser("~/.argos/skills"))
        memory_dir = Path(os.path.expanduser("~/.argos/memory"))
        eval_base = Path(os.path.expanduser("~/.argos/dreams/eval"))

        # per-run 隔离栈的 loop_factory（() -> AgentLoop）；EvalRunner 期望
        # loop_factory(model_tier) → loop，故包一层吞掉 tier（Dream 内不分档）。
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
                    system="你是技能文档撰写者。只输出文字,不输出代码。",
                ),
                timeout=60.0,
            )

        async def _dream_bcast(ev: dict) -> None:
            # T8 已留契约注释：caller 必须注入 run_id。Dream 事件走 _conductor 虚拟通道。
            payload = {**ev, "run_id": CONDUCTOR_RUN_ID}
            self._manager.store.append(CONDUCTOR_RUN_ID, payload)
            await self._manager.fanout(CONDUCTOR_RUN_ID, payload)

        self._dream_pipeline = DreamPipeline(
            candidates_root=DEFAULT_ROOT,
            skills_root=skills_root,
            memory_dir=memory_dir,
            dreams_dir=dreams_dir,
            runner_factory=_runner_factory,
            narrate=_narrate,
            broadcast_fn=_dream_bcast,
        )
        return self._dream_pipeline

    async def _start_dream(self, writer):
        """启动一次 Dream（confirm 与 POST /dream/run 共用）。

        返回 False 表示已发送错误响应（503/409），caller 不再追加任何响应。
        返回 True 表示 pipeline 任务已被派生（诚实：create_task 已调用）。

        TOCTOU 守卫：pipeline.is_running 只在 run() 协程体持锁后才为 True，
        而 create_task 派生的协程要到事件循环下一拍才执行。两个并发请求都可能
        在协程被调度前读到 is_running=False → 都发 202。为此在"检查通过"和
        "create_task"之间（无 await，原子窗口）同步设置 self._dream_starting=True，
        第二个请求看到 _dream_starting=True 就直接 409。done_callback 复位标志。
        """
        pipeline = self._get_dream_pipeline()
        if pipeline is None:
            await self._send_error(
                writer, 503, "no_worker_key",
                "daemon 未配置 API key，无法执行 Dream。请运行 `argos setup` 配置模型 key 后重启 daemon。",
            )
            return False
        # 三重守卫：
        #   pipeline.is_running   —— 本进程锁已持有(daemon 自己在跑)
        #   self._dream_starting  —— 本进程任务已派生但协程尚未持锁(TOCTOU 窗口)
        #   cross_process_busy()  —— 另一进程(CLI)正持跨进程文件锁(review#4):
        #     否则 pipeline.run() 因跨进程锁返 None 是异步发生,daemon 已回 202 却没真跑。
        if pipeline.is_running or self._dream_starting or pipeline.cross_process_busy():
            await self._send_error(
                writer, 409, "dream_busy", "已有一次夜间整合在跑，请稍后再试。",
            )
            return False
        # 从检查通过到 create_task 之间无 await —— 单线程事件循环不可被抢占，原子。
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
        """confirm 一个 action=dream 的 suggestion → 路由 DreamPipeline（而非 create_run）。

        503 no_worker_key / 409 dream_busy / 202 dream_started。202 时 pop suggestion +
        广播 suggestion_confirmed（dream=True，走 _conductor 通道）。
        """
        started = await self._start_dream(writer)
        if not started:
            return  # 503 / 409 已发送，suggestion 不消费（可稍后重试）
        # 已启动：从 pending 移除（confirm 后不再 pending）
        self._conductor.pop_suggestion(suggestion_id)
        # 广播 confirm 事件（审计可见性，走 _conductor 虚拟通道）
        confirm_ev = {
            "kind": "suggestion_confirmed",
            "suggestion_id": suggestion_id,
            "run_id": CONDUCTOR_RUN_ID,
            "dream": True,
            "ts": time.time(),
        }
        self._manager.store.append(CONDUCTOR_RUN_ID, confirm_ev)
        await self._manager.fanout(CONDUCTOR_RUN_ID, confirm_ev)
        await self._send_json(writer, 202, {
            "state": "dream_started",
            "suggestion_id": suggestion_id,
        })

    async def _handle_dream_run(self, writer, headers):
        """POST /dream/run — owner 手动触发一次 Dream（无 suggestion）。"""
        if await self._require_owner(writer, headers) is None:
            return
        started = await self._start_dream(writer)
        if not started:
            return  # 503 / 409 已发送
        await self._send_json(writer, 202, {"state": "dream_started"})

    async def _handle_dream_report(self, writer, headers):
        """GET /dream/report — 读最新 Dream 报告（dreams 目录最新 .jsonl 的最后一行）。

        目录空 / 无文件 / 无有效行 → 200 {"report": null}（诚实空态，不假装有报告）。
        """
        if await self._require_owner(writer, headers) is None:
            return
        report = self._read_latest_dream_report()
        await self._send_json(writer, 200, {"report": report})

    def _read_latest_dream_report(self) -> dict | None:
        """读 dreams 目录最新 .jsonl 文件的最后一行 JSON。无 → None（诚实空态）。"""
        dreams_dir = self._dreams_dir()
        try:
            if not dreams_dir.exists():
                return None
            files = sorted(dreams_dir.glob("*.jsonl"))
            if not files:
                return None
            # 文件名是 YYYY-MM-DD.jsonl → 字典序即时间序，取最新
            latest = files[-1]
            last_obj: dict | None = None
            for line in latest.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    last_obj = json.loads(line)
                except json.JSONDecodeError:
                    continue  # 跳过坏行，不让一行毁掉整份报告
            return last_obj
        except Exception as e:  # noqa: BLE001 — 读报告失败诚实降级为空态
            log.warning("dream report 读取失败(降级空态): %s", e)
            return None

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
        # 订阅新事件。keepalive 周期 2s:断连只能在【下一次写】时被发现
        # (BrokenPipe),15s 周期意味着客户端断开后 server 端最多挂 15s 才感知
        # —— 每个 SSE 测试 teardown 白等 15s,daemon 资源也多挂 15s。2s 是
        # 感知延迟与空转写之间的平衡(本地 socket,写开销可忽略)。
        q = self._manager.subscribe(run_id)
        try:
            while True:
                try:
                    ev = await asyncio.wait_for(q.get(), timeout=2.0)
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
