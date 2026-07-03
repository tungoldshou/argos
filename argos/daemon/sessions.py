from __future__ import annotations

import asyncio
import time
import uuid
from dataclasses import dataclass
from typing import Literal


HEARTBEAT_TIMEOUT_S: float = 30.0

SessionRole = Literal["owner", "observer"]


@dataclass
class SessionRecord:
    session_id: str
    last_heartbeat: float
    created_at: float
    role: SessionRole = "observer"
    last_active_run_id: str | None = None


class SessionRegistry:
    """UUID4 session + heartbeat + 30s expiry + role + promote(spec §2.5 + #5b §7)。"""

    def __init__(self, heartbeat_timeout_s: float = HEARTBEAT_TIMEOUT_S):
        self._sessions: dict[str, SessionRecord] = {}
        self._lock = asyncio.Lock()
        self._timeout = heartbeat_timeout_s

    async def create(self) -> SessionRecord:
        async with self._lock:
            role: SessionRole = "owner" if not self._sessions else "observer"
            rec = SessionRecord(
                session_id=str(uuid.uuid4()),
                last_heartbeat=time.time(),
                created_at=time.time(),
                role=role,
            )
            self._sessions[rec.session_id] = rec
            return rec

    async def heartbeat(self, session_id: str) -> bool:
        async with self._lock:
            rec = self._sessions.get(session_id)
            if rec is None:
                return False
            rec.last_heartbeat = time.time()
            return True

    def get(self, session_id: str) -> SessionRecord | None:
        return self._sessions.get(session_id)

    async def remove(self, session_id: str) -> None:
        async with self._lock:
            self._sessions.pop(session_id, None)

    async def promote_oldest_observer_after_remove(self, removed_id: str) -> str | None:
        async with self._lock:
            removed = self._sessions.pop(removed_id, None)
            if removed is None:
                return None
            if removed.role != "owner":
                return None
            observers = [r for r in self._sessions.values() if r.role == "observer"]
            if not observers:
                return None
            oldest = min(observers, key=lambda r: r.created_at)
            oldest.role = "owner"
            return oldest.session_id

    def is_alive(self, session_id: str, now: float | None = None) -> bool:
        if now is None:
            now = time.time()
        rec = self._sessions.get(session_id)
        if rec is None:
            return False
        return (now - rec.last_heartbeat) < self._timeout

    def active_count(self, now: float | None = None) -> int:
        if now is None:
            now = time.time()
        return sum(1 for r in self._sessions.values()
                   if (now - r.last_heartbeat) < self._timeout)

    def list_active(self, now: float | None = None) -> list[SessionRecord]:
        if now is None:
            now = time.time()
        return [r for r in self._sessions.values()
                if (now - r.last_heartbeat) < self._timeout]

    async def reap_expired(self) -> int:
        now = time.time()
        async with self._lock:
            expired = [sid for sid, r in self._sessions.items()
                       if (now - r.last_heartbeat) >= self._timeout]
            owner_expired = any(
                self._sessions[sid].role == "owner" for sid in expired
            )
            for sid in expired:
                self._sessions.pop(sid, None)
            if owner_expired:
                observers = [r for r in self._sessions.values() if r.role == "observer"]
                if observers:
                    min(observers, key=lambda r: r.created_at).role = "owner"
            return len(expired)

    def other_sessions(self, exclude: str, now: float | None = None) -> list[SessionRecord]:
        if now is None:
            now = time.time()
        return [r for r in self._sessions.values()
                if r.session_id != exclude
                and (now - r.last_heartbeat) < self._timeout]
