"""ArgosStore(SHARED INTERFACE CONTRACT §2)——单文件 SQLite 持久化地基。

~/.argos/argos.db(ARGOS_DB_PATH 可覆盖,测试用)。WAL + 写抖动重试 + 每 50 写
PASSIVE checkpoint。七表见 schema.sql。CJK 召回:sqlite-vec 向量(语义主路径,
对 CJK 最稳健,spec §5.3)+ FTS5 trigram 字面。embedding 源无关(§5.4)。

一份事件三用(spec §12.6):append_event 序列化进 events 表 → replay 重建。
诚实召回(spec §5.6):recall 返回 (MemoryRecord, reason) 二元组,reason 如实标
「为什么召回」;embedding 不可用 → 降级 FTS5,绝不假装搜过。
"""
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

if TYPE_CHECKING:
    from argos.protocol.events import Event
    from argos.memory.embedding import Embedder

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
    def __init__(self, db_path: str | None = None, *, embedder: "Embedder | None" = None) -> None:
        self._path = db_path or _default_db_path()
        Path(self._path).parent.mkdir(parents=True, exist_ok=True)
        self._writes = 0
        self.vec_enabled = False
        self._embedder = embedder  # source-agnostic (§5.4); None → recall 降级 FTS5
        self._con = self._connect()
        self._init_schema()

    # ── 连接 + 扩展加载 ──────────────────────────────────────────────────
    def _connect(self) -> sqlite3.Connection:
        con = sqlite3.connect(self._path, timeout=5.0, check_same_thread=False)
        con.row_factory = sqlite3.Row
        con.execute("PRAGMA journal_mode=WAL")
        con.execute("PRAGMA synchronous=NORMAL")
        # M-5:不设 PRAGMA foreign_keys=ON —— schema 未声明 FK 列,该 PRAGMA 是 no-op 且误导。
        # 引用完整性 MVP 由应用层保证(loop 先建 session 再 append 其 messages/events)。
        con.execute("PRAGMA busy_timeout=3000")  # 叠加应用层重试,双保险(spec §5.2 Step 3)
        self._load_vec(con)
        return con

    def _load_vec(self, con: sqlite3.Connection) -> None:
        """尝试加载 sqlite-vec(向量召回主路径)。缺扩展 → fail-soft,recall 退 FTS5。

        M-3:try/finally 确保 load-extension 始终被重新关闭(即使 sqlite_vec.load 抛错)。
        """
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

    def _write_txn(self, statements: list[tuple[str, tuple]]) -> None:
        """M-4:多条写在同一事务内一次性提交(全成或全不成),共享 _write 的锁退避重试。

        任一语句失败 → rollback,整笔不落盘;locked/busy → 整笔退避重试。
        提交后按写入语句数推进 _writes 与 checkpoint 计数(与单写一致计费)。
        """
        last_exc: Exception | None = None
        for attempt in range(_RETRY_MAX):
            try:
                for sql, params in statements:
                    self._con.execute(sql, params)
                self._con.commit()
                self._writes += len(statements)
                if self._writes % _CHECKPOINT_EVERY < len(statements):
                    # 本笔写跨过了 _CHECKPOINT_EVERY 的倍数 → 做一次 PASSIVE checkpoint
                    self._con.execute("PRAGMA wal_checkpoint(PASSIVE)")
                return
            except sqlite3.OperationalError as e:
                try:
                    self._con.rollback()  # 清掉部分事务,下一轮重试从干净状态开始
                except Exception:
                    pass
                if "locked" not in str(e).lower() and "busy" not in str(e).lower():
                    raise
                last_exc = e
                time.sleep(random.uniform(_RETRY_MIN_MS, _RETRY_MAX_MS) / 1000.0)
            except Exception:
                try:
                    self._con.rollback()  # 非锁错误也清事务,避免脏的半提交
                except Exception:
                    pass
                raise
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

    def ensure_session(self, session_id: str, *, title: str = "", model: str = "",
                       system_snapshot: str = "") -> None:
        """幂等创建【指定 id】的 session —— loop/TUI 用稳定 session_id 驱动 event sourcing/replay/resume
        (create_session 自生成 uuid,不接受指定 id;此方法补上"按既定 id 落 session 行"这一环)。
        已存在则 no-op(resume 复用同一 session,不覆盖)。"""
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

    # ── messages(契约 §2)──────────────────────────────────────────────────
    def append_message(self, session_id: str, *, role: str, content: str,
                        tool_calls_json: str = "", token_count: int = 0) -> str:
        mid = uuid.uuid4().hex[:12]
        ts = time.time()
        # M-4:message 行 + FTS 行同事务一次提交(原子),崩溃不会留下无 FTS 索引的孤儿消息
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
        """按时间顺序还原该 session 的对话消息线程(供 loop 跨轮重发)。
        只取模型对话角色 user/assistant;system/tool 行不进模型 messages(它们是元数据)。"""
        cur = self._con.execute(
            "SELECT role, content FROM messages WHERE session_id = ? "
            "AND role IN ('user','assistant') ORDER BY ts, rowid",
            (session_id,),
        )
        return [{"role": r["role"], "content": r["content"]} for r in cur.fetchall()]

    def compact_messages(self, session_id: str, *, keep_recent: int = 5) -> None:
        """长上下文压缩:把老的 user/assistant 消息折叠成一条摘要,保留最近 keep_recent 条逐字。
        删旧行(messages + FTS 同删保持一致),插摘要(用最早那条的 ts,排在最近之前)。
        MVP:截断式占位摘要(取各条前 60 字拼接);真 LLM 摘要可后续增强。"""
        cur = self._con.execute(
            "SELECT message_id, content, ts FROM messages WHERE session_id = ? "
            "AND role IN ('user','assistant') ORDER BY ts, rowid",
            (session_id,),
        )
        rows = cur.fetchall()
        if len(rows) <= keep_recent:
            return
        old = rows[:-keep_recent]
        summary = "(早期对话摘要)" + " / ".join((r["content"] or "")[:60] for r in old)
        old_ids = [r["message_id"] for r in old]
        ph = ",".join("?" * len(old_ids))
        sid = uuid.uuid4().hex[:12]
        summary_ts = old[0]["ts"]   # 用最早 ts → 摘要排在保留的最近消息之前
        self._write_txn([
            (f"DELETE FROM messages WHERE message_id IN ({ph})", tuple(old_ids)),
            (f"DELETE FROM messages_fts WHERE message_id IN ({ph})", tuple(old_ids)),
            ("INSERT INTO messages(message_id, session_id, role, content, tool_calls_json, ts, token_count) "
             "VALUES (?,?,?,?,?,?,?)", (sid, session_id, "user", summary, "", summary_ts, 0)),
            ("INSERT INTO messages_fts(content, message_id, session_id) VALUES (?,?,?)",
             (summary, sid, session_id)),
        ])

    # ── events(event sourcing,契约 §2 / spec §12.6)──────────────────────
    def append_event(self, session_id: str, event: "Event") -> None:
        from argos.protocol.events import serialize_event, event_kind
        self._write(
            "INSERT INTO events(session_id, kind, blob, ts) VALUES (?,?,?,?)",
            (session_id, event_kind(event), serialize_event(event), time.time()),
        )

    def replay(self, session_id: str) -> "ReplayState":
        """重放 events 重建状态(/resume,spec §5.8)。session 不存在 → KeyError。"""
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

    # ── FTS5 字面/CJK 搜(契约 §2 / spec §5.3)──────────────────────────────
    @staticmethod
    def _fts_quote(q: str) -> str:
        """把 query 包成 FTS5 字符串字面量,内部双引号转义 → 防 FTS5 语法注入/崩溃。"""
        escaped = q.replace('"', '""')
        return f'"{escaped}"'

    def search(self, q: str, *, limit: int = 20) -> list["MessageRow"]:
        """FTS5 trigram 字面/CJK 全文搜,join 回 messages 取完整行。坏 query → 空列表(降级)。"""
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
            return []  # FTS5 解析异常 → 诚实返空,不崩
        return [
            MessageRow(
                message_id=r["message_id"], session_id=r["session_id"], role=r["role"],
                content=r["content"], tool_calls_json=r["tool_calls_json"],
                ts=r["ts"], token_count=r["token_count"],
            )
            for r in rows
        ]

    # ── 可解释召回(契约 §2 / spec §5.6)──────────────────────────────────
    @staticmethod
    def _index_text(rec: "MemoryRecord") -> str:
        """memory 一条 → 索引文本:goal | verdict | model(沿用旧 memory._index_text)。"""
        return f"{rec.goal} | {rec.verdict or 'unknown'} | {rec.model or ''}"

    @staticmethod
    def _cosine(a: list[float], b: list[float]) -> float:
        """纯 Python 余弦(避免 numpy),0 向量保护(沿用旧 memory._cosine)。"""
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

    def recall(self, goal: str, *, k: int = 3, sim_min: float = 0.4
               ) -> list[tuple["MemoryRecord", str]]:
        """诚实召回(spec §5.6):(记录, 为什么召回)。embedding 不可用 → 降级 LIKE,reason 标注。"""
        if not goal.strip():
            return []
        recs = self._load_memories(limit=200)
        if not recs:
            return []
        # 主路径:embedding 语义召回
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
                    parts = [f"goal 相似 {sim:.2f}"]
                    if r.verdict:
                        parts.append(f"verdict={r.verdict}")
                    if r.model:
                        parts.append(f"模型 {r.model}")
                    out.append((r, "命中：" + " + ".join(parts)))
                return out
            except Exception:
                pass  # embedding 调用失败 → 落到下面 LIKE 降级
        # 降级路径:FTS5 不覆盖 memory 表 → 对 goal 做字面包含(LIKE),reason 诚实标降级
        # M-1:转义 LIKE 通配符 %/_ 与转义符自身,防止它们被当通配符
        g = goal.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        like = f"%{g}%"
        rows = self._con.execute(
            "SELECT * FROM memory WHERE goal LIKE ? ESCAPE '\\' ORDER BY ts DESC LIMIT ?", (like, k)
        ).fetchall()
        return [
            (
                MemoryRecord(id=r["id"], goal=r["goal"], verdict=r["verdict"],
                             model=r["model"], fact=r["fact"], ts=r["ts"]),
                "命中：embedding 不可用,降级字面匹配（goal 含查询串）",
            )
            for r in rows
        ]

    # ── migrate_jsonl(契约 §2 / spec §5.2)──────────────────────────────────
    def migrate_jsonl(self, jsonl_path: str | None = None) -> int:
        """一次性非破坏迁入旧 ~/.argos/memory.jsonl → memory 表。返回新迁入条数。

        INSERT OR IGNORE 按 id 去重 → 幂等可重跑;坏行跳过;不删源文件(非破坏)。
        None → 读 ARGOS_MEMORY_FILE 环境变量或默认 ~/.argos/memory.jsonl。
        """
        path = Path(
            jsonl_path
            or os.environ.get("ARGOS_MEMORY_FILE")
            or str(Path.home() / ".argos" / "memory.jsonl")
        )
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
                continue  # 坏行跳过(沿用旧 load_memories 容错)
            rid = rec.get("id")
            if not rid:
                continue
            try:
                ts = float(rec.get("ts") or 0.0)
            except (TypeError, ValueError):
                ts = 0.0  # 坏 ts → 0,不中断迁移(I-1:否则其后记录静默丢失)
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
