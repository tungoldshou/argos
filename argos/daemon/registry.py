from __future__ import annotations

import asyncio
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from argos.daemon.state_machine import TERMINAL_STATES


@dataclass
class RunEntry:
    run_id: str
    state: str
    goal: str
    workspace: str
    worktree_path: str | None = None
    created_at: float = 0.0
    updated_at: float = 0.0
    tokens_in: int = 0
    tokens_out: int = 0
    cost_usd: float | None = None
    focus_session_id: str | None = None
    task: asyncio.Task | None = field(default=None, repr=False)
    pause_event: asyncio.Event = field(default=None, repr=False)

    def __post_init__(self) -> None:
        if self.pause_event is None:
            ev = asyncio.Event()
            ev.set()
            self.pause_event = ev


class RunRegistry:

    def __init__(self, *, max_concurrent: int = 5, max_history: int = 100):
        self._entries: dict[str, RunEntry] = {}
        self._max_concurrent = max_concurrent
        self._max_history = max_history
        self._lock = asyncio.Lock()
        self._sem = asyncio.Semaphore(max_concurrent)
        self._acquired_count: dict[str, int] = {}

    @property
    def max_concurrent(self) -> int:
        return self._max_concurrent

    @property
    def max_history(self) -> int:
        return self._max_history

    @property
    def active_count(self) -> int:
        return sum(1 for e in self._entries.values() if e.state not in TERMINAL_STATES)

    @property
    def sem(self) -> asyncio.Semaphore:
        return self._sem

    @property
    def size(self) -> int:
        return len(self._entries)

    async def register(
        self, *, run_id: str, goal: str, workspace: str,
        worktree_path: str | None = None,
    ) -> RunEntry:
        now = time.time()
        entry = RunEntry(
            run_id=run_id, state="pending", goal=goal, workspace=workspace,
            worktree_path=worktree_path,
            created_at=now, updated_at=now,
        )
        async with self._lock:
            self._entries[run_id] = entry
        return entry

    def get(self, run_id: str) -> RunEntry | None:
        return self._entries.get(run_id)

    def list(self, *, state: str | None = None) -> list[RunEntry]:
        if state is None:
            return list(self._entries.values())
        return [e for e in self._entries.values() if e.state == state]

    def mark(self, *, run_id: str, state: str) -> None:
        e = self._entries.get(run_id)
        if e is None:
            return
        e.state = state
        e.updated_at = time.time()

    def add_cost(
        self, *, run_id: str, tokens_in_delta: int = 0,
        tokens_out_delta: int = 0, cost_usd_delta: float | None = None,
    ) -> None:
        e = self._entries.get(run_id)
        if e is None:
            return
        e.tokens_in += int(tokens_in_delta)
        e.tokens_out += int(tokens_out_delta)
        if cost_usd_delta is not None:
            e.cost_usd = (e.cost_usd or 0.0) + cost_usd_delta
        e.updated_at = time.time()

    def set_focus(self, *, run_id: str, session_id: str | None) -> None:
        e = self._entries.get(run_id)
        if e is None:
            return
        e.focus_session_id = session_id
        e.updated_at = time.time()

    def get_focus(self, *, run_id: str) -> str | None:
        e = self._entries.get(run_id)
        return e.focus_session_id if e is not None else None

    # ── semaphore ────────────────────────────────────────────────────

    async def acquire_slot(self) -> None:
        await self._sem.acquire()

    def release_slot(self) -> None:
        try:
            self._sem.release()
        except ValueError:
            pass

    def has_capacity(self) -> bool:
        return not self._sem.locked() and self._sem._value > 0  # type: ignore[attr-defined]

    # ── cleanup / max_history ───────────────────────────────────────

    async def cleanup(self, *, run_id: str, terminal_state: str) -> None:
        async with self._lock:
            e = self._entries.get(run_id)
            if e is None:
                return
            e.state = terminal_state
            e.updated_at = time.time()
        self.release_slot()
        await self._enforce_max_history()

    async def _enforce_max_history(self) -> None:
        async with self._lock:
            terminal = [e for e in self._entries.values() if e.state in TERMINAL_STATES]
            if len(terminal) <= self._max_history:
                return
            terminal.sort(key=lambda e: e.created_at)
            to_remove = terminal[: len(terminal) - self._max_history]
            for e in to_remove:
                self._entries.pop(e.run_id, None)

    def snapshot(self) -> list[dict[str, Any]]:
        out = []
        for e in self._entries.values():
            out.append({
                "run_id": e.run_id, "state": e.state, "goal": e.goal,
                "workspace": e.workspace, "worktree_path": e.worktree_path,
                "created_at": e.created_at, "updated_at": e.updated_at,
                "tokens_in": e.tokens_in, "tokens_out": e.tokens_out,
                "cost_usd": e.cost_usd, "focus_session_id": e.focus_session_id,
            })
        return out


# ── module-level helper ────────────────────────────────────────────────


def new_run_id() -> str:
    return uuid.uuid4().hex[:12]
