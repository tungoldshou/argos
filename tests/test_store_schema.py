"""Phase 2:建库 + 七表 + WAL + schema_version + sqlite-vec 加载标志。"""
import sqlite3

import pytest

from argos_agent.memory.store import ArgosStore, SCHEMA_VERSION


EXPECTED_TABLES = {
    "sessions", "messages", "events", "messages_fts",
    "memory", "state_meta", "schema_version",
}


def _open(tmp_path):
    return ArgosStore(db_path=str(tmp_path / "argos.db"))


def test_creates_all_seven_tables(tmp_path):
    store = _open(tmp_path)
    con = sqlite3.connect(str(tmp_path / "argos.db"))
    names = {r[0] for r in con.execute(
        "select name from sqlite_master where type in ('table','view')"
    )}
    con.close()
    store.close()
    assert EXPECTED_TABLES <= names, f"缺表:{EXPECTED_TABLES - names}"


def test_wal_mode_enabled(tmp_path):
    store = _open(tmp_path)
    mode = store._con.execute("pragma journal_mode").fetchone()[0]
    store.close()
    assert mode.lower() == "wal"


def test_schema_version_recorded(tmp_path):
    store = _open(tmp_path)
    v = store._con.execute("select version from schema_version").fetchone()[0]
    store.close()
    assert v == SCHEMA_VERSION


def test_env_path_override(tmp_path, monkeypatch):
    p = tmp_path / "from_env.db"
    monkeypatch.setenv("ARGOS_DB_PATH", str(p))
    store = ArgosStore()  # db_path=None → 读 ARGOS_DB_PATH
    store.close()
    assert p.exists()


def test_vec_loaded_flag_is_bool(tmp_path):
    store = _open(tmp_path)
    # sqlite-vec 已实测可加载;flag 应为 True(若环境缺扩展则 False,但不崩)
    assert isinstance(store.vec_enabled, bool)
    store.close()


def test_reopen_idempotent(tmp_path):
    # 二次打开同库不应重复建表报错(CREATE IF NOT EXISTS)
    _open(tmp_path).close()
    store2 = _open(tmp_path)
    store2.close()
