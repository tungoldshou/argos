from __future__ import annotations

import json
import math
import os
import random
import sqlite3
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Literal

from argos.core.types import VerdictStatus, Phase
from argos.i18n import t

if TYPE_CHECKING:
    from argos.protocol.events import Event
    from argos.memory.embedding import Embedder

SCHEMA_VERSION = 1
_SCHEMA_PATH = Path(__file__).with_name("schema.sql")

_RETRY_MAX = 15
_RETRY_MIN_MS = 20
_RETRY_MAX_MS = 150
_CHECKPOINT_EVERY = 50


def _default_db_path() -> str:
    if path := os.environ.get("ARGOS_DB_PATH"):
        return str(Path(path).expanduser())
    from argos import config

    return str(Path(config.get("ARGOS_CONFIG_DIR") or (Path.home() / ".argos")).expanduser() / "argos.db")


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
    def __init__(self, db_path: str | None = None, *, embedder: "Embedder | None" = None) -> None:
        self._path = db_path or _default_db_path()
        Path(self._path).parent.mkdir(parents=True, exist_ok=True)
        self._writes = 0
        self.vec_enabled = False
        self._embedder = embedder
        self._con = self._connect()
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        con = sqlite3.connect(self._path, timeout=5.0, check_same_thread=False)
        con.row_factory = sqlite3.Row
        con.execute("PRAGMA journal_mode=WAL")
        con.execute("PRAGMA synchronous=NORMAL")
        con.execute("PRAGMA busy_timeout=3000")
        self._load_vec(con)
        return con

    def _load_vec(self, con: sqlite3.Connection) -> None:
        try:
            import sqlite_vec

            con.enable_load_extension(True)
            sqlite_vec.load(con)
            self.vec_enabled = True
        except Exception:
            self.vec_enabled = False
        finally:
            try:
                con.enable_load_extension(False)
            except Exception:
                pass

    def _init_schema(self) -> None:
        self._con.executescript(_SCHEMA_PATH.read_text(encoding="utf-8"))
        row = self._con.execute("SELECT version FROM schema_version").fetchone()
        if row is None:
            self._con.execute("INSERT INTO schema_version(version) VALUES (?)", (SCHEMA_VERSION,))
        self._con.commit()

    def _write(self, sql: str, params: tuple = ()) -> sqlite3.Cursor:
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

    def _write_txn(self, statements: list[tuple[str, tuple]]) -> None:
        last_exc: Exception | None = None
        for attempt in range(_RETRY_MAX):
            try:
                for sql, params in statements:
                    self._con.execute(sql, params)
                self._con.commit()
                self._writes += len(statements)
                if self._writes % _CHECKPOINT_EVERY < len(statements):
                    self._con.execute("PRAGMA wal_checkpoint(PASSIVE)")
                return
            except sqlite3.OperationalError as e:
                try:
                    self._con.rollback()
                except Exception:
                    pass
                if "locked" not in str(e).lower() and "busy" not in str(e).lower():
                    raise
                last_exc = e
                time.sleep(random.uniform(_RETRY_MIN_MS, _RETRY_MAX_MS) / 1000.0)
            except Exception:
                try:
                    self._con.rollback()
                except Exception:
                    pass
                raise
        raise last_exc  # type: ignore[misc]

    def create_session(self, *, title: str, model: str, system_snapshot: str,
                        parent: str | None = None) -> str:
        sid = uuid.uuid4().hex[:12]
        self._write(
            "INSERT INTO sessions(session_id, parent, title, model, system_snapshot, started_at) "
            "VALUES (?,?,?,?,?,?)",
            (sid, parent, title, model, system_snapshot, time.time()),
        )
        return sid

    def ensure_session(self, session_id: str, *, title: str = "", model: str = "",
                       system_snapshot: str = "") -> None:
        self._write(
            "INSERT OR IGNORE INTO sessions(session_id, parent, title, model, system_snapshot, started_at) "
            "VALUES (?,?,?,?,?,?)",
            (session_id, None, title, model, system_snapshot, time.time()),
        )

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

    def append_message(self, session_id: str, *, role: str, content: str,
                        tool_calls_json: str = "", token_count: int = 0) -> str:
        mid = uuid.uuid4().hex[:12]
        ts = time.time()
        self._write_txn([
            (
                "INSERT INTO messages(message_id, session_id, role, content, tool_calls_json, ts, token_count) "
                "VALUES (?,?,?,?,?,?,?)",
                (mid, session_id, role, content, tool_calls_json, ts, token_count),
            ),
            (
                "INSERT INTO messages_fts(content, message_id, session_id) VALUES (?,?,?)",
                (content, mid, session_id),
            ),
        ])
        return mid

    def get_messages(self, session_id: str) -> list[dict]:
        cur = self._con.execute(
            "SELECT role, content FROM messages WHERE session_id = ? "
            "AND role IN ('user','assistant') ORDER BY ts, rowid",
            (session_id,),
        )
        return [{"role": r["role"], "content": r["content"]} for r in cur.fetchall()]

    def compact_messages(self, session_id: str, *, keep_recent: int = 5) -> None:
        cur = self._con.execute(
            "SELECT message_id, content, ts FROM messages WHERE session_id = ? "
            "AND role IN ('user','assistant') ORDER BY ts, rowid",
            (session_id,),
        )
        rows = cur.fetchall()
        if len(rows) <= keep_recent:
            return
        old = rows[:-keep_recent]
        summary = t("mem.summary_prefix") + " / ".join((r["content"] or "")[:60] for r in old)
        old_ids = [r["message_id"] for r in old]
        ph = ",".join("?" * len(old_ids))
        sid = uuid.uuid4().hex[:12]
        summary_ts = old[0]["ts"]
        self._write_txn([
            (f"DELETE FROM messages WHERE message_id IN ({ph})", tuple(old_ids)),
            (f"DELETE FROM messages_fts WHERE message_id IN ({ph})", tuple(old_ids)),
            ("INSERT INTO messages(message_id, session_id, role, content, tool_calls_json, ts, token_count) "
             "VALUES (?,?,?,?,?,?,?)", (sid, session_id, "user", summary, "", summary_ts, 0)),
            ("INSERT INTO messages_fts(content, message_id, session_id) VALUES (?,?,?)",
             (summary, sid, session_id)),
        ])

    def append_event(self, session_id: str, event: "Event") -> None:
        from argos.protocol.events import serialize_event, event_kind
        self._write(
            "INSERT INTO events(session_id, kind, blob, ts) VALUES (?,?,?,?)",
            (session_id, event_kind(event), serialize_event(event), time.time()),
        )

    def replay(self, session_id: str) -> "ReplayState":
        from argos.protocol.events import deserialize_event, event_kind
        session = self.get_session(session_id)
        if session is None:
            raise KeyError(f"session not found: {session_id}")
        msg_rows = self._con.execute(
            "SELECT * FROM messages WHERE session_id=? ORDER BY ts, rowid", (session_id,)
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

    @staticmethod
    def _fts_quote(q: str) -> str:
        escaped = q.replace('"', '""')
        return f'"{escaped}"'

    def search(self, q: str, *, limit: int = 20) -> list["MessageRow"]:
        if not q.strip():
            return []
        try:
            rows = self._con.execute(
                "SELECT m.* FROM messages_fts f "
                "JOIN messages m ON m.message_id = f.message_id "
                "WHERE messages_fts MATCH ? "
                "ORDER BY rank LIMIT ?",
                (self._fts_quote(q), limit),
            ).fetchall()
        except sqlite3.OperationalError:
            return []
        return [
            MessageRow(
                message_id=r["message_id"], session_id=r["session_id"], role=r["role"],
                content=r["content"], tool_calls_json=r["tool_calls_json"],
                ts=r["ts"], token_count=r["token_count"],
            )
            for r in rows
        ]

    @staticmethod
    def _index_text(rec: "MemoryRecord") -> str:
        return f"{rec.goal} | {rec.verdict or 'unknown'} | {rec.model or ''}"

    @staticmethod
    def _cosine(a: list[float], b: list[float]) -> float:
        s = na = nb = 0.0
        for x, y in zip(a, b):
            s += x * y
            na += x * x
            nb += y * y
        if na == 0.0 or nb == 0.0:
            return 0.0
        return s / math.sqrt(na * nb)

    def _load_memories(self, limit: int = 200) -> list["MemoryRecord"]:
        rows = self._con.execute(
            "SELECT * FROM memory ORDER BY ts DESC LIMIT ?", (limit,)
        ).fetchall()
        return [
            MemoryRecord(id=r["id"], goal=r["goal"], verdict=r["verdict"],
                         model=r["model"], fact=r["fact"], ts=r["ts"])
            for r in rows
        ]

    async def arecall(self, goal: str, *, k: int = 3, sim_min: float = 0.4
                      ) -> list[tuple["MemoryRecord", str]]:
        import asyncio
        if not goal.strip():
            return []
        recs = self._load_memories(limit=200)
        if not recs:
            return []
        if self._embedder is not None and hasattr(self._embedder, "aembed"):
            try:
                goal_emb = (await self._embedder.aembed([goal]))[0]  # type: ignore[attr-defined]
                texts = [self._index_text(r) for r in recs]
                rec_embs = await self._embedder.aembed(texts)  # type: ignore[attr-defined]
                scored: list[tuple[float, "MemoryRecord"]] = [
                    (self._cosine(goal_emb, e), r) for e, r in zip(rec_embs, recs)
                ]
                scored.sort(key=lambda x: x[0], reverse=True)
                out: list[tuple["MemoryRecord", str]] = []
                for sim, r in scored[:k]:
                    if sim < sim_min:
                        continue
                    parts = [t("mem.recall_hit_sim", sim=sim)]
                    if r.verdict:
                        parts.append(f"verdict={r.verdict}")
                    if r.model:
                        parts.append(t("mem.recall_hit_model", model=r.model))
                    out.append((r, t("mem.recall_hit_prefix") + " + ".join(parts)))
                return out
            except Exception:
                pass
        return await asyncio.to_thread(self.recall, goal, k=k, sim_min=sim_min)

    def recall(self, goal: str, *, k: int = 3, sim_min: float = 0.4
               ) -> list[tuple["MemoryRecord", str]]:
        if not goal.strip():
            return []
        recs = self._load_memories(limit=200)
        if not recs:
            return []
        if self._embedder is not None:
            try:
                goal_emb = self._embedder.embed([goal])[0]
                texts = [self._index_text(r) for r in recs]
                rec_embs = self._embedder.embed(texts)
                scored: list[tuple[float, "MemoryRecord"]] = [
                    (self._cosine(goal_emb, e), r) for e, r in zip(rec_embs, recs)
                ]
                scored.sort(key=lambda x: x[0], reverse=True)
                out: list[tuple["MemoryRecord", str]] = []
                for sim, r in scored[:k]:
                    if sim < sim_min:
                        continue
                    parts = [t("mem.recall_hit_sim", sim=sim)]
                    if r.verdict:
                        parts.append(f"verdict={r.verdict}")
                    if r.model:
                        parts.append(t("mem.recall_hit_model", model=r.model))
                    out.append((r, t("mem.recall_hit_prefix") + " + ".join(parts)))
                return out
            except Exception:
                pass
        g = goal.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        like = f"%{g}%"
        rows = self._con.execute(
            "SELECT * FROM memory WHERE goal LIKE ? ESCAPE '\\' ORDER BY ts DESC LIMIT ?", (like, k)
        ).fetchall()
        return [
            (
                MemoryRecord(id=r["id"], goal=r["goal"], verdict=r["verdict"],
                             model=r["model"], fact=r["fact"], ts=r["ts"]),
                t("mem.recall_hit_fallback"),
            )
            for r in rows
        ]

    def migrate_jsonl(self, jsonl_path: str | None = None) -> int:
        path = Path(
            jsonl_path
            or os.environ.get("ARGOS_MEMORY_FILE")
            or str(Path.home() / ".argos" / "memory.jsonl")
        ).expanduser()
        if not path.exists():
            return 0
        migrated = 0
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            rid = rec.get("id")
            if not rid:
                continue
            try:
                ts = float(rec.get("ts") or 0.0)
            except (TypeError, ValueError):
                ts = 0.0
            cur = self._write(
                "INSERT OR IGNORE INTO memory(id, goal, verdict, model, fact, ts) "
                "VALUES (?,?,?,?,?,?)",
                (rid, rec.get("goal") or "", rec.get("verdict"), rec.get("model"),
                 rec.get("fact"), ts),
            )
            if cur.rowcount > 0:
                migrated += 1
        return migrated

    def close(self) -> None:
        try:
            self._con.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        except Exception:
            pass
        self._con.close()
