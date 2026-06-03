-- Argos 持久化七表(spec §5.2)。全部 IF NOT EXISTS,二次打开幂等。

CREATE TABLE IF NOT EXISTS schema_version (
    version INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS sessions (
    session_id      TEXT PRIMARY KEY,
    parent          TEXT,                 -- lineage:派生自哪个 session
    title           TEXT NOT NULL DEFAULT '',
    model           TEXT NOT NULL DEFAULT '',
    system_snapshot TEXT NOT NULL DEFAULT '',
    tokens_in       INTEGER NOT NULL DEFAULT 0,
    tokens_out      INTEGER NOT NULL DEFAULT 0,
    cost_usd        REAL NOT NULL DEFAULT 0.0,
    started_at      REAL NOT NULL,
    ended_at        REAL
);
CREATE INDEX IF NOT EXISTS idx_sessions_started ON sessions(started_at DESC);

CREATE TABLE IF NOT EXISTS messages (
    message_id      TEXT PRIMARY KEY,
    session_id      TEXT NOT NULL,
    role            TEXT NOT NULL,        -- user|assistant|system|tool
    content         TEXT NOT NULL DEFAULT '',
    tool_calls_json TEXT NOT NULL DEFAULT '',  -- tool_calls/code_actions/receipts JSON
    ts              REAL NOT NULL,
    token_count     INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_messages_session ON messages(session_id, ts);

CREATE TABLE IF NOT EXISTS events (
    rowid_pk   INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    kind       TEXT NOT NULL,
    blob       TEXT NOT NULL,             -- serialize_event() 的 JSON 串
    ts         REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_events_session ON events(session_id, rowid_pk);

-- FTS5 字面/CJK 全文搜(spec §5.3)。trigram tokenizer:对 >=3 字命中稳;
-- 2 字 CJK 命中弱 → 语义召回主路径走 sqlite-vec(见 store.recall)。
-- 若 sqlite-better-trigram dylib 存在,store 会改用 better-trigram(更稳 CJK 字面)。
CREATE VIRTUAL TABLE IF NOT EXISTS messages_fts USING fts5(
    content,
    message_id UNINDEXED,
    session_id UNINDEXED,
    tokenize = 'trigram'
);

CREATE TABLE IF NOT EXISTS memory (
    id      TEXT PRIMARY KEY,
    goal    TEXT NOT NULL DEFAULT '',
    verdict TEXT,                          -- passed|failed|unverifiable|NULL
    model   TEXT,
    fact    TEXT,
    ts      REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_memory_ts ON memory(ts DESC);

CREATE TABLE IF NOT EXISTS state_meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
