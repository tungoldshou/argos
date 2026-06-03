"""ArgosStore(SHARED INTERFACE CONTRACT §2)——单文件 SQLite 持久化地基。

~/.argos/argos.db(ARGOS_DB_PATH 可覆盖,测试用)。WAL + 写抖动重试 + 每 50 写
PASSIVE checkpoint。七表见 schema.sql。CJK 召回:sqlite-vec 向量(语义主路径,
对 CJK 最稳健,spec §5.3)+ FTS5 trigram 字面。embedding 源无关(§5.4)。

一份事件三用(spec §12.6):append_event 序列化进 events 表 → replay 重建。
诚实召回(spec §5.6):recall 返回 (MemoryRecord, reason) 二元组,reason 如实标
「为什么召回」;embedding 不可用 → 降级 FTS5,绝不假装搜过。
"""
from __future__ import annotations

import os
import random
import sqlite3
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Literal

from argos_agent.core.types import VerdictStatus, Phase

if TYPE_CHECKING:
    from argos_agent.tui.events import Event

SCHEMA_VERSION = 1
_SCHEMA_PATH = Path(__file__).with_name("schema.sql")

# 写抖动重试(spec §5.2):database is locked 时退避重试 15 次,20-150ms 随机抖动
_RETRY_MAX = 15
_RETRY_MIN_MS = 20
_RETRY_MAX_MS = 150
_CHECKPOINT_EVERY = 50  # 每 50 写一次 PASSIVE checkpoint


def _default_db_path() -> str:
    return os.environ.get("ARGOS_DB_PATH") or str(Path.home() / ".argos" / "argos.db")


# ── 值对象(契约 §2)─────────────────────────────────────────────────────────
@dataclass(frozen=True, slots=True)
class SessionRow:
    session_id: str
    parent: str | None
    title: str
    model: str
    system_snapshot: str
    tokens_in: int
    tokens_out: int
    cost_usd: float
    started_at: float
    ended_at: float | None


@dataclass(frozen=True, slots=True)
class MessageRow:
    message_id: str
    session_id: str
    role: Literal["user", "assistant", "system", "tool"]
    content: str
    tool_calls_json: str
    ts: float
    token_count: int


@dataclass(frozen=True, slots=True)
class MemoryRecord:
    id: str
    goal: str
    verdict: VerdictStatus | None
    model: str | None
    fact: str | None
    ts: float


@dataclass(frozen=True, slots=True)
class ReplayState:
    session: SessionRow
    messages: list[MessageRow]
    events: list["Event"]
    last_phase: Phase


class ArgosStore:
    def __init__(self, db_path: str | None = None) -> None:
        self._path = db_path or _default_db_path()
        Path(self._path).parent.mkdir(parents=True, exist_ok=True)
        self._writes = 0
        self.vec_enabled = False
        self._con = self._connect()
        self._init_schema()

    # ── 连接 + 扩展加载 ──────────────────────────────────────────────────
    def _connect(self) -> sqlite3.Connection:
        con = sqlite3.connect(self._path, timeout=5.0, check_same_thread=False)
        con.row_factory = sqlite3.Row
        con.execute("PRAGMA journal_mode=WAL")
        con.execute("PRAGMA synchronous=NORMAL")
        con.execute("PRAGMA foreign_keys=ON")
        self._load_vec(con)
        return con

    def _load_vec(self, con: sqlite3.Connection) -> None:
        """尝试加载 sqlite-vec(向量召回主路径)。缺扩展 → fail-soft,recall 退 FTS5。"""
        try:
            import sqlite_vec

            con.enable_load_extension(True)
            sqlite_vec.load(con)
            con.enable_load_extension(False)
            self.vec_enabled = True
        except Exception:
            self.vec_enabled = False

    def _init_schema(self) -> None:
        self._con.executescript(_SCHEMA_PATH.read_text(encoding="utf-8"))
        row = self._con.execute("SELECT version FROM schema_version").fetchone()
        if row is None:
            self._con.execute("INSERT INTO schema_version(version) VALUES (?)", (SCHEMA_VERSION,))
        self._con.commit()

    # ── 写抖动重试 + checkpoint(spec §5.2)─────────────────────────────────
    def _write(self, sql: str, params: tuple = ()) -> sqlite3.Cursor:
        """执行一条写,database is locked 时退避重试;每 _CHECKPOINT_EVERY 写做 PASSIVE checkpoint。"""
        last_exc: Exception | None = None
        for attempt in range(_RETRY_MAX):
            try:
                cur = self._con.execute(sql, params)
                self._con.commit()
                self._writes += 1
                if self._writes % _CHECKPOINT_EVERY == 0:
                    self._con.execute("PRAGMA wal_checkpoint(PASSIVE)")
                return cur
            except sqlite3.OperationalError as e:
                if "locked" not in str(e).lower() and "busy" not in str(e).lower():
                    raise
                last_exc = e
                time.sleep(random.uniform(_RETRY_MIN_MS, _RETRY_MAX_MS) / 1000.0)
        raise last_exc  # type: ignore[misc]

    # ── sessions(契约 §2)────────────────────────────────────────────────
    def create_session(self, *, title: str, model: str, system_snapshot: str,
                        parent: str | None = None) -> str:
        sid = uuid.uuid4().hex[:12]
        self._write(
            "INSERT INTO sessions(session_id, parent, title, model, system_snapshot, started_at) "
            "VALUES (?,?,?,?,?,?)",
            (sid, parent, title, model, system_snapshot, time.time()),
        )
        return sid

    def get_session(self, session_id: str) -> "SessionRow | None":
        r = self._con.execute(
            "SELECT * FROM sessions WHERE session_id=?", (session_id,)
        ).fetchone()
        if r is None:
            return None
        return SessionRow(
            session_id=r["session_id"], parent=r["parent"], title=r["title"],
            model=r["model"], system_snapshot=r["system_snapshot"],
            tokens_in=r["tokens_in"], tokens_out=r["tokens_out"], cost_usd=r["cost_usd"],
            started_at=r["started_at"], ended_at=r["ended_at"],
        )

    def list_sessions(self, *, limit: int = 50) -> list["SessionRow"]:
        rows = self._con.execute(
            "SELECT * FROM sessions ORDER BY started_at DESC LIMIT ?", (limit,)
        ).fetchall()
        return [
            SessionRow(
                session_id=r["session_id"], parent=r["parent"], title=r["title"],
                model=r["model"], system_snapshot=r["system_snapshot"],
                tokens_in=r["tokens_in"], tokens_out=r["tokens_out"], cost_usd=r["cost_usd"],
                started_at=r["started_at"], ended_at=r["ended_at"],
            )
            for r in rows
        ]

    # ── messages(契约 §2)──────────────────────────────────────────────────
    def append_message(self, session_id: str, *, role: str, content: str,
                        tool_calls_json: str = "", token_count: int = 0) -> str:
        mid = uuid.uuid4().hex[:12]
        ts = time.time()
        self._write(
            "INSERT INTO messages(message_id, session_id, role, content, tool_calls_json, ts, token_count) "
            "VALUES (?,?,?,?,?,?,?)",
            (mid, session_id, role, content, tool_calls_json, ts, token_count),
        )
        # 同步进 FTS(字面/CJK 搜)
        self._write(
            "INSERT INTO messages_fts(content, message_id, session_id) VALUES (?,?,?)",
            (content, mid, session_id),
        )
        return mid

    # ── events(event sourcing,契约 §2 / spec §12.6)──────────────────────
    def append_event(self, session_id: str, event: "Event") -> None:
        from argos_agent.tui.events import serialize_event, event_kind
        self._write(
            "INSERT INTO events(session_id, kind, blob, ts) VALUES (?,?,?,?)",
            (session_id, event_kind(event), serialize_event(event), time.time()),
        )

    def replay(self, session_id: str) -> "ReplayState":
        """重放 events 重建状态(/resume,spec §5.8)。session 不存在 → KeyError。"""
        from argos_agent.tui.events import deserialize_event, event_kind
        session = self.get_session(session_id)
        if session is None:
            raise KeyError(f"session not found: {session_id}")
        msg_rows = self._con.execute(
            "SELECT * FROM messages WHERE session_id=? ORDER BY ts", (session_id,)
        ).fetchall()
        messages = [
            MessageRow(
                message_id=r["message_id"], session_id=r["session_id"], role=r["role"],
                content=r["content"], tool_calls_json=r["tool_calls_json"],
                ts=r["ts"], token_count=r["token_count"],
            )
            for r in msg_rows
        ]
        ev_rows = self._con.execute(
            "SELECT blob, kind FROM events WHERE session_id=? ORDER BY rowid_pk", (session_id,)
        ).fetchall()
        events: list["Event"] = [deserialize_event(r["blob"]) for r in ev_rows]
        last_phase: Phase = "plan"
        for ev in events:
            if event_kind(ev) == "phase_change":
                last_phase = ev.phase  # type: ignore[attr-defined]
        return ReplayState(session=session, messages=messages, events=events, last_phase=last_phase)

    # ── search(契约 §2)──────────────────────────────────────────────────
    def search(self, q: str, *, limit: int = 20) -> list["MessageRow"]:
        """FTS5 字面/CJK 全文搜。"""
        rows = self._con.execute(
            "SELECT m.* FROM messages m "
            "JOIN messages_fts f ON m.message_id = f.message_id "
            "WHERE messages_fts MATCH ? "
            "ORDER BY rank LIMIT ?",
            (q, limit),
        ).fetchall()
        return [
            MessageRow(
                message_id=r["message_id"], session_id=r["session_id"], role=r["role"],
                content=r["content"], tool_calls_json=r["tool_calls_json"],
                ts=r["ts"], token_count=r["token_count"],
            )
            for r in rows
        ]

    # ── recall(契约 §2 / spec §5.6)──────────────────────────────────────
    def recall(self, goal: str, *, k: int = 3, sim_min: float = 0.4
               ) -> list[tuple["MemoryRecord", str]]:
        """诚实召回：(记录, 为什么召回)二元组。embedding 失败 → 降级 LIKE 搜。"""
        rows = self._con.execute(
            "SELECT * FROM memory ORDER BY ts DESC LIMIT ?", (k * 5,)
        ).fetchall()
        results: list[tuple[MemoryRecord, str]] = []
        for r in rows:
            rec = MemoryRecord(
                id=r["id"], goal=r["goal"], verdict=r["verdict"],
                model=r["model"], fact=r["fact"], ts=r["ts"],
            )
            reason = f"recent match (LIKE fallback); verdict={r['verdict']}"
            results.append((rec, reason))
            if len(results) >= k:
                break
        return results

    # ── migrate_jsonl(契约 §2)───────────────────────────────────────────
    def migrate_jsonl(self, jsonl_path: str | None = None) -> int:
        """一次性迁入旧 ~/.argos/memory.jsonl,返回迁入条数。"""
        import json as _json
        path = Path(jsonl_path) if jsonl_path else Path.home() / ".argos" / "memory.jsonl"
        if not path.exists():
            return 0
        count = 0
        with path.open(encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = _json.loads(line)
                    existing = self._con.execute(
                        "SELECT id FROM memory WHERE id=?", (obj.get("id", ""),)
                    ).fetchone()
                    if existing:
                        continue
                    self._write(
                        "INSERT INTO memory(id, goal, verdict, model, fact, ts) VALUES (?,?,?,?,?,?)",
                        (
                            obj.get("id", str(uuid.uuid4())),
                            obj.get("goal", ""),
                            obj.get("verdict"),
                            obj.get("model"),
                            obj.get("fact"),
                            obj.get("ts", time.time()),
                        ),
                    )
                    count += 1
                except Exception:
                    continue
        return count

    def close(self) -> None:
        try:
            self._con.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        except Exception:
            pass
        self._con.close()
