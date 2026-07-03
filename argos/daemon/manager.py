from __future__ import annotations

import asyncio
import logging
import time
import uuid
from pathlib import Path
from typing import Any

from argos.daemon.events import RunCheckpoint, RunFailure, RunMeta
from argos.daemon.index import IndexEntry, StateIndex
from argos.daemon.state_machine import (
    TERMINAL_STATES, InvalidTransition, read_state, transition,
)
from argos.daemon.store import CorruptionError, RunStore

log = logging.getLogger(__name__)


def _prune_snapshot(run_id: str, snapshot_root: "Path") -> None:
    candidate = snapshot_root / f"run-{run_id}.tar"
    if candidate.exists():
        try:
            candidate.unlink()
            log.debug("recover: pruned snapshot for terminal run %s", run_id)
        except OSError as exc:
            log.warning("recover: failed to prune snapshot %s: %s", candidate, exc)


class RunManager:

    def __init__(self, *, runs_dir: Path, index_path: Path):
        self._store = RunStore(runs_dir)
        self._index = StateIndex(index_path)
        self._index.load()
        self._lock = asyncio.Lock()
        # run_id → pause/cancel/suspend requests
        self._pause_requested: dict[str, asyncio.Event] = {}
        self._cancel_requested: dict[str, bool] = {}
        self._suspend_requested: dict[str, bool] = {}
        # run_id → (asyncio.Queue, ...) — fan-out
        self._subscribers: dict[str, set[asyncio.Queue]] = {}

    @property
    def store(self) -> RunStore:
        return self._store

    @property
    def index(self) -> StateIndex:
        return self._index

    @property
    def runs_dir(self) -> Path:
        return self._store.runs_dir

    def close(self) -> None:
        self._index.save()

    # ── Run lifecycle ────────────────────────────────────────────────

    async def create_run(
        self,
        *,
        goal: str,
        workspace: str = "",
        model: str = "",
        approval_level: str = "confirm",
        session_id: str = "",
        max_steps: int = 200,
    ) -> str:
        if not goal or not isinstance(goal, str):
            raise ValueError("goal must be non-empty string")
        run_id = uuid.uuid4().hex[:12]
        now = time.time()
        meta = RunMeta(
            run_id=run_id, goal=goal, workspace=workspace, model=model,
            created_at=now, approval_level=approval_level, max_steps=max_steps,
            session_id=session_id,
        )
        async with self._lock:
            self._store.append(run_id, meta.to_dict())
            self._index.upsert(
                run_id, state="pending", goal=goal, workspace=workspace,
                created_at=now, updated_at=now, last_event_seq=0,
                model=model, approval_level=approval_level,
                session_id=session_id,
            )
            self._index.save()
            self._pause_requested[run_id] = asyncio.Event()
            self._pause_requested[run_id].set()
            self._cancel_requested[run_id] = False
            self._suspend_requested[run_id] = False
        return run_id

    def get_run(self, run_id: str) -> IndexEntry | None:
        return self._index.get(run_id)

    def list_runs(self, state: str | None = None) -> list[dict[str, Any]]:
        out = []
        for rid, entry in self._index.list():
            if state is not None and entry.state != state:
                continue
            out.append({
                "run_id": rid,
                "state": entry.state,
                "goal": entry.goal,
                "workspace": entry.workspace,
                "created_at": entry.created_at,
                "updated_at": entry.updated_at,
                "last_event_seq": entry.last_event_seq,
            })
        return out

    def events_count(self, run_id: str) -> int:
        n = 0
        for _ in self._store.replay(run_id):
            n += 1
        return n


    async def request_pause(self, run_id: str) -> bool:
        async with self._lock:
            current = read_state(run_id, self._index)
            if current != "running":
                return False
            ev = self._pause_requested.get(run_id)
            if ev is None:
                return False
            ev.clear()
        return True

    async def request_resume(self, run_id: str) -> bool:
        async with self._lock:
            current = read_state(run_id, self._index)
            if current not in ("paused", "suspended"):
                return False
            ev = self._pause_requested.setdefault(run_id, asyncio.Event())
            ev.set()
        return True

    async def request_cancel(self, run_id: str) -> bool:
        async with self._lock:
            current = read_state(run_id, self._index)
            if current in TERMINAL_STATES:
                return False
            self._cancel_requested[run_id] = True
        return True

    def is_cancel_requested(self, run_id: str) -> bool:
        return self._cancel_requested.get(run_id, False)

    async def request_suspend(self, run_id: str) -> bool:
        async with self._lock:
            current = read_state(run_id, self._index)
            if current != "running":
                return False
            self._suspend_requested[run_id] = True
        return True

    def is_suspend_requested(self, run_id: str) -> bool:
        return self._suspend_requested.get(run_id, False)

    def pause_event(self, run_id: str) -> asyncio.Event:
        return self._pause_requested.setdefault(run_id, asyncio.Event())

    def mark_running(self, run_id: str) -> None:
        transition(
            current=None, target="running", index=self._index, run_id=run_id,
            store=self._store, reason="start",
        )
        self._index.save()

    def mark_paused(self, run_id: str, last_step: int, msg_count: int, last_event_seq: int) -> None:
        self._store.append(run_id, RunCheckpoint(
            ts=time.time(), last_step=last_step, messages_count=msg_count,
            last_event_seq=last_event_seq,
        ).to_dict())
        # 2) state_change
        transition(
            current=None, target="paused", index=self._index, run_id=run_id,
            store=self._store, reason="user_esc",
        )
        self._index.save()

    def mark_resumed(self, run_id: str) -> None:
        transition(
            current=None, target="running", index=self._index, run_id=run_id,
            store=self._store, reason="user_resume",
        )
        self._index.save()

    def mark_completed(self, run_id: str) -> None:
        transition(
            current=None, target="completed", index=self._index, run_id=run_id,
            store=self._store, reason="loop_finished",
        )
        self._index.save()

    def mark_cancelled(self, run_id: str) -> None:
        transition(
            current=None, target="cancelled", index=self._index, run_id=run_id,
            store=self._store, reason="cancelled",
        )
        self._index.save()

    def mark_failed(self, run_id: str, error: str, error_type: str, traceback: str, step: int) -> None:
        self._store.append(run_id, RunFailure(
            ts=time.time(), error=error, error_type=error_type,
            traceback=traceback, step=step,
        ).to_dict())
        transition(
            current=None, target="failed", index=self._index, run_id=run_id,
            store=self._store, reason=error_type,
        )
        self._index.save()

    def mark_suspended(self, run_id: str, last_step: int, msg_count: int, last_event_seq: int) -> None:
        self._store.append(run_id, RunCheckpoint(
            ts=time.time(), last_step=last_step, messages_count=msg_count,
            last_event_seq=last_event_seq,
        ).to_dict())
        transition(
            current=None, target="suspended", index=self._index, run_id=run_id,
            store=self._store, reason="tui_exit",
        )
        self._index.save()

    # ── SSE fan-out ──────────────────────────────────────────────────

    def subscribe(self, run_id: str, maxsize: int = 1024) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=maxsize)
        self._subscribers.setdefault(run_id, set()).add(q)
        return q

    def unsubscribe(self, run_id: str, q: asyncio.Queue) -> None:
        subs = self._subscribers.get(run_id)
        if subs is not None:
            subs.discard(q)
            if not subs:
                self._subscribers.pop(run_id, None)

    async def fanout(self, run_id: str, event: dict[str, Any]) -> None:
        subs = self._subscribers.get(run_id, set())
        for q in list(subs):
            try:
                q.put_nowait(event)
            except asyncio.QueueFull:
                log.warning("fanout: subscriber queue full for run %s, dropping event", run_id)


    def recover(self) -> dict[str, str]:
        from argos.core.snapshot import SNAPSHOT_ROOT

        recovered: dict[str, str] = {}
        for rid in self._store.list_runs():
            if rid.startswith("_"):
                continue
            try:
                last = self._store.last_state(rid)
            except CorruptionError as exc:
                log.warning("recover: skipping corrupt run file %s: %s", rid, exc)
                continue
            cur = read_state(rid, self._index)
            if cur in TERMINAL_STATES:
                _prune_snapshot(rid, SNAPSHOT_ROOT)
                continue
            if cur is None or cur == "pending":
                if last is None or last == "pending":
                    transition(
                        current=None, target="cancelled", index=self._index, run_id=rid,
                        store=self._store, reason="recover_no_state",
                    )
                    recovered[rid] = "cancelled"
                    _prune_snapshot(rid, SNAPSHOT_ROOT)
                continue
            if cur == "running":
                transition(
                    current=None, target="suspended", index=self._index, run_id=rid,
                    store=self._store, reason="recover_sigkill",
                )
                recovered[rid] = "suspended"
        self._index.save()
        return recovered
