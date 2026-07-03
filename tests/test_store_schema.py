import sqlite3

import pytest

from argos.memory.store import ArgosStore, SCHEMA_VERSION


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
    store = ArgosStore()
    store.close()
    assert p.exists()


def test_env_path_override_expands_user_home(tmp_path, monkeypatch):
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    monkeypatch.setenv("HOME", str(fake_home))
    monkeypatch.setenv("ARGOS_DB_PATH", "~/argos.db")

    store = ArgosStore()
    store.close()

    assert (fake_home / "argos.db").exists()


def test_default_db_path_honors_argos_config_dir(tmp_path, monkeypatch):
    from argos import config as C

    cfg = tmp_path / "cfg"
    monkeypatch.delenv("ARGOS_DB_PATH", raising=False)
    monkeypatch.setenv("ARGOS_CONFIG_DIR", str(cfg))
    monkeypatch.setattr(C, "_ENV", {})

    store = ArgosStore()
    store.close()

    assert (cfg / "argos.db").exists()


def test_db_path_env_override_wins_over_argos_config_dir(tmp_path, monkeypatch):
    from argos import config as C

    cfg = tmp_path / "cfg"
    db = tmp_path / "explicit.db"
    monkeypatch.setenv("ARGOS_CONFIG_DIR", str(cfg))
    monkeypatch.setenv("ARGOS_DB_PATH", str(db))
    monkeypatch.setattr(C, "_ENV", {})

    store = ArgosStore()
    store.close()

    assert db.exists()
    assert not (cfg / "argos.db").exists()


def test_vec_loaded_flag_is_bool(tmp_path):
    store = _open(tmp_path)
    assert isinstance(store.vec_enabled, bool)
    store.close()


def test_reopen_idempotent(tmp_path):
    _open(tmp_path).close()
    store2 = _open(tmp_path)
    store2.close()
