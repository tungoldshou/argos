"""SessionRegistry:多 TUI 互斥基础设施(spec §2.5 Session 协议)。

本期 #5a 单 TUI 限定,本模块为 #5b 铺路:实现 session_id 注册/注销/heartbeat/30s 过期,
但单 TUI 时 all write-capable(无 read-only 降级 — #5b 才启用)。

字段:
  _sessions: dict[session_id, SessionRecord]
  _lock: asyncio.Lock(并发更新)
"""
from __future__ import annotations

import asyncio
import time
import uuid
from dataclasses import dataclass


HEARTBEAT_TIMEOUT_S: float = 30.0


@dataclass
class SessionRecord:
    session_id: str
    last_heartbeat: float
    created_at: float


class SessionRegistry:
    """UUID4 session + heartbeat + 30s expiry(spec §2.5)。"""

    def __init__(self, heartbeat_timeout_s: float = HEARTBEAT_TIMEOUT_S):
        self._sessions: dict[str, SessionRecord] = {}
        self._lock = asyncio.Lock()
        self._timeout = heartbeat_timeout_s

    async def create(self) -> SessionRecord:
        async with self._lock:
            rec = SessionRecord(
                session_id=str(uuid.uuid4()),
                last_heartbeat=time.time(),
                created_at=time.time(),
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

    async def remove(self, session_id: str) -> None:
        async with self._lock:
            self._sessions.pop(session_id, None)

    def is_alive(self, session_id: str, now: float | None = None) -> bool:
        """检查 session 是否在 heartbeat timeout 内(无锁 — 读快照,过期可后台清扫)。"""
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
        """清扫过期 session(> timeout 未心跳);返清扫数。"""
        now = time.time()
        async with self._lock:
            expired = [sid for sid, r in self._sessions.items()
                       if (now - r.last_heartbeat) >= self._timeout]
            for sid in expired:
                self._sessions.pop(sid, None)
            return len(expired)

    def other_sessions(self, exclude: str, now: float | None = None) -> list[SessionRecord]:
        """除自己外的活跃 session(供 /health 报 other_tuis)。"""
        if now is None:
            now = time.time()
        return [r for r in self._sessions.values()
                if r.session_id != exclude
                and (now - r.last_heartbeat) < self._timeout]
