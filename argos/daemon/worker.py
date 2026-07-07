from __future__ import annotations

import asyncio
import dataclasses
import json
import logging
import os
import time
import traceback as tb_mod
from pathlib import Path
from typing import AsyncIterator, Any

from argos.daemon.manager import RunManager
from argos.daemon.state_machine import TERMINAL_STATES
import argos.runtime as _runtime
from argos.i18n import t as _t

log = logging.getLogger(__name__)


def _to_event_dict(ev: Any) -> dict:
    if isinstance(ev, dict):
        return dict(ev)
    if dataclasses.is_dataclass(ev) and not isinstance(ev, type):
        try:
            from argos.protocol.events import serialize_event
            blob = serialize_event(ev)  # type: ignore[arg-type]
            parsed = json.loads(blob)
            result = {"kind": parsed["kind"]}
            result.update(parsed.get("data", {}))
            return result
        except Exception as exc:  # noqa: BLE001
            log.warning("_to_event_dict: serialize failed (%s), fallback asdict", exc)
            return {**dataclasses.asdict(ev), "kind": getattr(type(ev), "kind", "unknown")}  # type: ignore[arg-type]
    return {"kind": "unknown", "_raw": str(ev)}



class DaemonApprovalGate:

    def __init__(self, real_gate: Any, *, timeout_s: float = 60.0,
                 run_id: str = "", manager: "RunManager | None" = None) -> None:
        self._gate = real_gate
        self._timeout_s = timeout_s
        self._run_id = run_id
        self._manager = manager
        self._pending_call_ids: set[str] = set()

    def set_permission_mode(self, mode: Any) -> None:
        self._gate.set_permission_mode(mode)

    def set_workspace(self, ws: Any) -> None:
        self._gate.set_workspace(ws)

    def set_session_id(self, sid: str) -> None:
        self._gate.set_session_id(sid)

    def set_decision_listener(self, fn: Any) -> None:
        self._gate.set_decision_listener(fn)

    def pending(self) -> list:
        return self._gate.pending()

    def has_pending_call(self, call_id: str) -> bool:
        return call_id in self._pending_call_ids

    async def request(self, action: str, args: dict, *, description: str,
                      risk: Any, timeout: float = 60.0,
                      call_id: str | None = None) -> Any:
        import uuid as _uuid
        if call_id is None:
            call_id = _uuid.uuid4().hex[:12]
        import time as _time
        from argos.approval import Decision as _Decision
        effective_timeout = min(timeout, self._timeout_s)
        self._pending_call_ids.add(call_id)
        try:
            inner_coro = self._gate.request(
                action, args, description=description, risk=risk,
                timeout=effective_timeout * 2,
                call_id=call_id,
            )
            inner_task = asyncio.ensure_future(inner_coro)
            await asyncio.sleep(0)

            if self._manager is not None:
                try:
                    await self._manager.fanout(self._run_id, {
                        "kind": "approval_request",
                        "call_id": call_id,
                        "action": action,
                        "args": args,
                        "description": description,
                        "risk": str(risk) if not isinstance(risk, str) else risk,
                        "run_id": self._run_id,
                        "ts": _time.time(),
                    })
                except Exception:  # noqa: BLE001
                    pass

            try:
                return await asyncio.wait_for(
                    asyncio.shield(inner_task),
                    timeout=effective_timeout,
                )
            except asyncio.TimeoutError:
                inner_task.cancel()
                try:
                    await inner_task
                except (asyncio.CancelledError, Exception):
                    pass
                self._gate.deny(call_id)
                msg = _t(
                    "daemon.srv.approval_timeout",
                    action=action,
                    run_id=self._run_id,
                    call_id=call_id,
                )
                log.warning("DaemonApprovalGate timeout fail-closed: %s", msg)
                if self._manager is not None:
                    try:
                        error_ev = {
                            "kind": "error",
                            "message": msg,
                            "chain": ["ApprovalTimeout", f"action={action!r}",
                                      f"call_id={call_id!r}"],
                        }
                        self._manager.store.append(self._run_id, error_ev)
                        await self._manager.fanout(self._run_id, error_ev)
                    except Exception:  # noqa: BLE001
                        pass
                return _Decision(kind="deny", reason=msg)
        finally:
            self._pending_call_ids.discard(call_id)

    def respond(self, call_id: str, kind: Any) -> bool:
        return self._gate.respond(call_id, kind)

    def approve(self, call_id: str) -> None:
        """backward-compat。"""
        self._gate.approve(call_id)

    def deny(self, call_id: str) -> None:
        """backward-compat。"""
        self._gate.deny(call_id)


class FakeLoop:

    def __init__(self, *, steps: int = 5, delay_s: float = 0.0):
        self._steps = steps
        self._delay = delay_s

    async def run(self, goal: str, session_id: str) -> AsyncIterator[dict]:
        for i in range(self._steps):
            if self._delay:
                await asyncio.sleep(self._delay)
            yield {"kind": "token_delta", "text": f"step {i}", "step": i}
            yield {"kind": "code_action", "code": f"# step {i}", "step": i}
            yield {"kind": "code_result", "stdout": "", "value_repr": "", "exc": "", "ok": True, "step": i}
        yield {"kind": "verify_verdict",
               "verdict": {"status": "passed", "reason": "fake"}}


class RunWorker:

    def __init__(self, *, run_id: str, manager: RunManager, loop_factory,
                 registry=None, worktree=None, gate=None,
                 run_stack_close=None, approval_timeout_s: float = 60.0,
                 ledger_store=None, snapshot=None, attachments=None,
                 initial_event_seq: int = 0, initial_step_count: int = 0):
        self.run_id = run_id
        self._manager = manager
        self._loop_factory = loop_factory
        self._loop = None
        # ponytail: resume-from-suspended restores these from RunCheckpoint so the
        # SSE cursor and step budget continue rather than restart from 0.
        self._event_seq = initial_event_seq
        self._step_count = initial_step_count
        self._message_count = 0
        self._current_phase = "act"
        self._task: asyncio.Task | None = None
        self._watchdog: asyncio.Task | None = None
        self._registry = registry
        self._worktree = worktree
        self._gate = gate
        self._approval_timeout_s = approval_timeout_s
        self._run_stack_close = run_stack_close
        self._ledger_store = ledger_store
        self._snapshot = snapshot
        self._attachments = list(attachments or [])
        self._ledger_seq = 0

    @property
    def event_seq(self) -> int:
        return self._event_seq

    @property
    def current_step(self) -> int:
        return self._step_count

    @property
    def gate(self) -> "DaemonApprovalGate | None":
        return self._gate  # type: ignore[return-value]

    def request_hard_cancel(self) -> bool:
        t = self._task
        if t is not None and not t.done():
            t.cancel()
            return True
        return False

    async def run(self) -> None:
        self._task = asyncio.current_task()
        entry = self._manager.get_run(self.run_id)
        if entry is None:
            log.warning("worker.run: run %s not found", self.run_id)
            return
        if entry.workspace:
            _ws_path = Path(entry.workspace).expanduser().resolve()
        else:
            _ws_path = _runtime._make_default_ctx().workspace
        _rt_ctx = _runtime.RunContext(workspace=_ws_path, verify_dir=_ws_path, project_mode=True)
        _rt_token = _runtime.set_context(_rt_ctx)
        try:
            self._watchdog = self._maybe_start_watchdog()
            if self._gate is not None and not isinstance(self._gate, DaemonApprovalGate):
                self._gate.set_workspace(entry.workspace or "")
                self._gate.set_session_id(f"run-{self.run_id}")
                self._gate = DaemonApprovalGate(
                    self._gate, timeout_s=self._approval_timeout_s,
                    run_id=self.run_id, manager=self._manager,
                )
            elif self._gate is not None:
                self._gate.set_workspace(entry.workspace or "")
                self._gate.set_session_id(f"run-{self.run_id}")
            # 1. mark_running
            self._manager.mark_running(self.run_id)
            if self._registry is not None:
                self._registry.mark(run_id=self.run_id, state="running")
            # 2. build loop
            self._loop = self._loop_factory()
            pause_event = self._manager.pause_event(self.run_id)
            # 4. drive
            _run_kwargs = {"attachments": self._attachments} if self._attachments else {}
            loop_session_id = entry.session_id or f"run-{self.run_id}"
            async for ev in self._loop.run(entry.goal, session_id=loop_session_id,
                                           **_run_kwargs):
                if self._manager.is_cancel_requested(self.run_id):
                    break
                ev_dict = _to_event_dict(ev)
                ev_kind = ev_dict.get("kind", "")
                if ev_kind in ("code_action", "phase_change"):
                    if self._manager.is_suspend_requested(self.run_id):
                        self._manager.mark_suspended(
                            self.run_id, last_step=self._step_count,
                            msg_count=self._message_count, last_event_seq=self._event_seq,
                        )
                        if self._registry is not None:
                            self._registry.mark(run_id=self.run_id, state="suspended")
                        await self._manager.fanout(self.run_id, {
                            "kind": "state_change",
                            "from": "running",
                            "to": "suspended",
                            "reason": "user_background",
                            "ts": time.time(),
                        })
                        return
                    if not pause_event.is_set():
                        self._manager.mark_paused(
                            self.run_id, last_step=self._step_count,
                            msg_count=self._message_count, last_event_seq=self._event_seq,
                        )
                        if self._registry is not None:
                            self._registry.mark(run_id=self.run_id, state="paused")
                        await self._manager.fanout(self.run_id, {
                            "kind": "state_change",
                            "from": "running",
                            "to": "paused",
                            "reason": "user_esc",
                            "ts": time.time(),
                        })
                        await pause_event.wait()
                        # resume
                        self._manager.mark_resumed(self.run_id)
                        if self._registry is not None:
                            self._registry.mark(run_id=self.run_id, state="running")
                        await self._manager.fanout(self.run_id, {
                            "kind": "state_change",
                            "from": "paused",
                            "to": "running",
                            "reason": "user_resume",
                            "ts": time.time(),
                        })
                if ev_kind == "code_action":
                    self._step_count += 1
                elif ev_kind == "token_delta":
                    self._message_count += 1
                elif ev_kind == "phase_change":
                    self._current_phase = ev_dict.get("phase", "act")
                elif ev_kind == "cost_update" and self._registry is not None:
                    try:
                        self._registry.add_cost(
                            run_id=self.run_id,
                            tokens_in_delta=int(ev_dict.get("tokens_in", 0)),
                            tokens_out_delta=int(ev_dict.get("tokens_out", 0)),
                            cost_usd_delta=ev_dict.get("cost_usd"),
                        )
                    except Exception as e:  # noqa: BLE001
                        log.warning("worker: cost add failed for %s: %s", self.run_id, e)
                self._event_seq = self._manager.store.append(self.run_id, ev_dict)
                self._manager.index.upsert(self.run_id, last_event_seq=self._event_seq)
                await self._manager.fanout(self.run_id, ev_dict)
                if ev_kind == "tool_receipt" and self._ledger_store is not None:
                    await self._maybe_append_ledger(ev_dict)
                elif ev_kind == "file_diff" and self._ledger_store is not None:
                    await self._maybe_append_ledger_for_file_diff(ev_dict)
            cur = self._manager.index.get(self.run_id)
            if cur is not None and cur.state not in ("completed", "failed", "cancelled"):
                if self._manager.is_cancel_requested(self.run_id):
                    self._manager.mark_cancelled(self.run_id)
                else:
                    self._manager.mark_completed(self.run_id)
            await self._maybe_run_learning_hook(entry)
        except asyncio.CancelledError:
            cur = self._manager.index.get(self.run_id)
            if cur is not None and cur.state not in ("completed", "failed", "cancelled"):
                self._manager.mark_cancelled(self.run_id)
            raise
        except Exception as e:  # noqa: BLE001
            log.exception("worker.run exception: %s", e)
            cur = self._manager.index.get(self.run_id)
            if cur is not None and cur.state not in ("completed", "failed", "cancelled"):
                self._manager.mark_failed(
                    self.run_id, error=str(e), error_type=type(e).__name__,
                    traceback=tb_mod.format_exc(), step=self._step_count,
                )
        finally:
            if self._watchdog is not None:
                self._watchdog.cancel()
                self._watchdog = None
            await self._emit_terminal_signal()
            _runtime.reset(_rt_token)
            if self._run_stack_close is not None:
                try:
                    self._run_stack_close()
                except Exception as _e:  # noqa: BLE001
                    log.warning("worker: run_stack_close failed for %s: %s", self.run_id, _e)
            await self._post_terminal_cleanup()

    def _maybe_start_watchdog(self) -> "asyncio.Task | None":
        raw = os.environ.get("ARGOS_RUN_TIMEOUT_S", "").strip()
        if not raw:
            return None
        try:
            timeout_s = float(raw)
        except ValueError:
            return None
        if timeout_s <= 0:
            return None
        return asyncio.create_task(self._watchdog_timer(timeout_s))

    async def _watchdog_timer(self, timeout_s: float) -> None:
        try:
            await asyncio.sleep(timeout_s)
        except asyncio.CancelledError:
            return
        log.warning(
            "worker: run %s 超过看门狗超时 %.1fs,硬取消", self.run_id, timeout_s
        )
        self.request_hard_cancel()

    async def _emit_terminal_signal(self) -> None:
        try:
            entry = self._manager.index.get(self.run_id)
            state = entry.state if entry is not None else None
            if state not in TERMINAL_STATES:
                return
            await self._manager.fanout(self.run_id, {
                "kind": "state_change",
                "from": "running",
                "to": state,
                "reason": "terminal",
                "ts": time.time(),
            })
        except Exception as e:  # noqa: BLE001
            log.warning("worker: 终态广播失败 for %s: %s", self.run_id, e)

    async def _maybe_append_ledger(self, ev_dict: dict) -> None:
        try:
            from argos.ledger.builder import build_entry
            from argos.protocol.events import LedgerEntryEvent

            receipt_data = ev_dict.get("receipt") or {}
            if not isinstance(receipt_data, dict):
                import dataclasses as _dc
                receipt_data = _dc.asdict(receipt_data)  # type: ignore[arg-type]

            if not receipt_data.get("action"):
                return

            class _FakeReceipt:
                def __init__(self, d: dict) -> None:
                    self.action = str(d.get("action", ""))
                    self.ts = float(d.get("ts", 0.0))
                    self.sig = str(d.get("sig", ""))

            fake_receipt = _FakeReceipt(receipt_data)

            undo_token: str | None = None
            if self._snapshot is not None:
                try:
                    snap_path = self._snapshot.tar_path
                    if snap_path.exists():
                        undo_token = str(snap_path)
                except Exception:  # noqa: BLE001
                    pass

            self._ledger_seq += 1
            entry = build_entry(
                receipt=fake_receipt,
                run_id=self.run_id,
                seq=self._ledger_seq,
                args={},
                undo_token=undo_token,
            )
            self._ledger_store.append(entry)  # type: ignore[union-attr]

            le_ev = LedgerEntryEvent(
                ts=entry.ts,
                run_id=entry.run_id,
                seq=entry.seq,
                action=entry.action,
                summary_human=entry.summary_human,
                risk=entry.risk,
                reversible=entry.reversible,
                undo_state=entry.undo_state,
            )
            from argos.protocol.events import serialize_event
            import json as _json
            parsed = _json.loads(serialize_event(le_ev))
            le_dict = {"kind": parsed["kind"]}
            le_dict.update(parsed.get("data", {}))
            self._event_seq += 1
            le_dict["_seq"] = self._event_seq
            self._manager.index.upsert(self.run_id, last_event_seq=self._event_seq)
            self._manager.store.append(self.run_id, le_dict)
            await self._manager.fanout(self.run_id, le_dict)
        except Exception as e:  # noqa: BLE001
            log.warning("worker: ledger append failed for %s: %s", self.run_id, e)

    async def _maybe_append_ledger_for_file_diff(self, ev_dict: dict) -> None:
        try:
            from argos.ledger.entry import LedgerEntry
            from argos.protocol.events import LedgerEntryEvent
            import os
            import time as _time

            path_str: str = str(ev_dict.get("path", ""))
            added: int = int(ev_dict.get("added", 0))
            removed: int = int(ev_dict.get("removed", 0))

            if not path_str:
                return

            basename = os.path.basename(path_str) or path_str

            undo_token: str | None = None
            reversible = "unknown"
            if self._snapshot is not None:
                try:
                    snap_path = self._snapshot.tar_path
                    if snap_path.exists():
                        undo_token = f"file:{path_str}"
                        reversible = "yes"
                except Exception:  # noqa: BLE001
                    pass

            undo_state = "available" if reversible == "yes" else "impossible"
            if added or removed:
                summary = _t("daemon.srv.ledger_modified_diff",
                             basename=basename, added=added, removed=removed)
            else:
                summary = _t("daemon.srv.ledger_modified", basename=basename)

            self._ledger_seq += 1
            entry = LedgerEntry(
                ts=_time.time(),
                run_id=self.run_id,
                seq=self._ledger_seq,
                action="file_diff",
                summary_human=summary,
                risk="low",
                reversible=reversible,  # type: ignore[arg-type]
                undo_token=undo_token,
                receipt_sig="",
                undo_state=undo_state,  # type: ignore[arg-type]
            )
            self._ledger_store.append(entry)  # type: ignore[union-attr]

            from argos.protocol.events import serialize_event
            import json as _json
            le_ev = LedgerEntryEvent(
                ts=entry.ts,
                run_id=entry.run_id,
                seq=entry.seq,
                action=entry.action,
                summary_human=entry.summary_human,
                risk=entry.risk,
                reversible=entry.reversible,
                undo_state=entry.undo_state,
            )
            parsed = _json.loads(serialize_event(le_ev))
            le_dict = {"kind": parsed["kind"]}
            le_dict.update(parsed.get("data", {}))
            self._event_seq += 1
            le_dict["_seq"] = self._event_seq
            self._manager.index.upsert(self.run_id, last_event_seq=self._event_seq)
            self._manager.store.append(self.run_id, le_dict)
            await self._manager.fanout(self.run_id, le_dict)
        except Exception as e:  # noqa: BLE001
            log.warning("worker: file_diff ledger append failed for %s: %s", self.run_id, e)

    async def _post_terminal_cleanup(self) -> None:
        try:
            cur = self._manager.index.get(self.run_id)
            if cur is None:
                return
            terminal = cur.state in ("completed", "failed", "cancelled", "suspended")
            if not terminal:
                return
            if self._worktree is not None:
                try:
                    self._worktree.cleanup(self.run_id)
                except Exception as e:  # noqa: BLE001
                    log.warning("worker: worktree cleanup failed: %s", e)
            if self._registry is not None:
                try:
                    await self._registry.cleanup(
                        run_id=self.run_id, terminal_state=cur.state,
                    )
                except Exception as e:  # noqa: BLE001
                    log.warning("worker: registry cleanup failed: %s", e)
        except Exception as e:  # noqa: BLE001
            log.warning("worker: post_terminal_cleanup failed for %s: %s", self.run_id, e)

    async def _maybe_run_learning_hook(self, entry) -> None:
        try:
            from argos.learning.hook import on_run_completed
            from argos.daemon.__main__ import _default_argos_dir

            verdict_status = "failed"
            verify_cmd: str | None = None
            self_verified: bool = False
            try:
                events = list(self._manager.store.replay(self.run_id))
                for ev in events:
                    if isinstance(ev, dict) and ev.get("kind") == "verify_verdict":
                        v = ev.get("verdict") or {}
                        if isinstance(v, dict):
                            verdict_status = v.get("status", verdict_status) or verdict_status
                            verify_cmd = v.get("verify_cmd") or verify_cmd
                            self_verified = bool(v.get("self_verified", False))
            except Exception:  # noqa: BLE001
                pass

            store_dir = self._manager.store.runs_dir()
            argos_dir = _default_argos_dir()
            skills_root = argos_dir / "skills"

            # ponytail: Loop-4 ORCHESTRATION is wired — promote() is reachable,
            # A=bare/B=hinted runners are correctly separated — but live A/B eval
            # is inert until EvalRunner._drive drives a real AgentLoop (v1.1
            # real-loop adapter, shared with Dream).  Real AgentLoop has only
            # `async def run`, no `run_sync`; _drive returns PASS_ERROR for both
            # A and B → b_passed(0) <= a_passed(0) → no_improvement → no skill
            # is ever auto-enabled in a live daemon.  Fails safe: never promotes,
            # never fakes a pass.  See runner.py:334 (v1.1 TODO) and
            # tests/learning/test_eval_runner_inert.py for the locked ceiling.
            _runner_factory = None
            if self._loop_factory is not None and self._worktree is not None:
                try:
                    from argos.eval.runner import EvalRunner
                    _eval_base = argos_dir / "eval" / "learning"
                    _wt = self._worktree
                    _lf = self._loop_factory

                    def _eval_loop_factory(model_tier: str, wt_path: str = "") -> Any:  # noqa: E731
                        """Return a loop caged to the eval worktree wt_path, not _ws_path."""
                        loop = _lf()
                        if wt_path:
                            from pathlib import Path as _Path
                            _ws = _Path(wt_path).expanduser().resolve()
                            _ws.mkdir(parents=True, exist_ok=True)
                            # Override workspace attrs (same pattern as server._make_run_loop_factory)
                            loop._workspace = _ws
                            loop._verify_dir = _ws
                        return loop

                    _base_runner = EvalRunner(
                        worktree=_wt,
                        base_dir=_eval_base,
                        loop_factory=_eval_loop_factory,
                    )
                    _runner_factory = lambda: _base_runner  # noqa: E731
                except Exception as _rf_err:  # noqa: BLE001
                    log.warning(
                        "worker: runner_factory build failed for %s, "
                        "falling back to candidate-staging: %s",
                        self.run_id, _rf_err,
                    )

            await on_run_completed(
                run_id=self.run_id,
                store_dir=store_dir,
                goal=getattr(entry, "goal", "") or "",
                verify_cmd=verify_cmd,
                verdict_status=verdict_status,
                self_verified=self_verified,
                skills_root=skills_root,
                candidates_root=argos_dir / "learning" / "candidates",
                workspace=(getattr(entry, "workspace", "") or None),
                runner_factory=_runner_factory,
                tasks=[],  # hook auto-builds EvalTask from workspace+verify_cmd
            )
        except Exception as e:  # noqa: BLE001
            log.warning("worker: learning hook failed for %s: %s", self.run_id, e)
