"""Internal documentation."""
import json

import pytest

from argos.memory.store import ArgosStore


def _write_jsonl(path, records):
    path.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in records), encoding="utf-8")


@pytest.fixture
def store(tmp_path):
    s = ArgosStore(db_path=str(tmp_path / "argos.db"))
    yield s
    s.close()


def test_migrate_inserts_all_records(store, tmp_path):
    jl = tmp_path / "memory.jsonl"
    _write_jsonl(jl, [
        {"id": "a1", "goal": "跑 pytest", "verdict": "passed", "model": "M2", "fact": None, "ts": 1.0},
        {"id": "b2", "goal": "写文档", "verdict": "failed", "model": "M2", "fact": "卡住了", "ts": 2.0},
    ])
    n = store.migrate_jsonl(str(jl))
    assert n == 2
    rows = store._con.execute("SELECT id, goal, verdict FROM memory ORDER BY ts").fetchall()
    assert [(r["id"], r["goal"], r["verdict"]) for r in rows] == [
        ("a1", "跑 pytest", "passed"), ("b2", "写文档", "failed")
    ]


def test_migrate_is_idempotent_by_id(store, tmp_path):
    jl = tmp_path / "memory.jsonl"
    _write_jsonl(jl, [{"id": "a1", "goal": "g", "verdict": "passed", "model": "m", "fact": None, "ts": 1.0}])
    assert store.migrate_jsonl(str(jl)) == 1
    assert store.migrate_jsonl(str(jl)) == 0
    cnt = store._con.execute("SELECT count(*) FROM memory").fetchone()[0]
    assert cnt == 1


def test_migrate_skips_bad_lines(store, tmp_path):
    jl = tmp_path / "memory.jsonl"
    jl.write_text(
        '{"id":"a1","goal":"g","verdict":"passed","model":"m","fact":null,"ts":1.0}\n'
        "这不是 JSON\n"
        '{"id":"b2","goal":"g2","verdict":null,"model":null,"fact":null,"ts":2.0}\n',
        encoding="utf-8",
    )
    assert store.migrate_jsonl(str(jl)) == 2


def test_migrate_does_not_delete_source(store, tmp_path):
    jl = tmp_path / "memory.jsonl"
    _write_jsonl(jl, [{"id": "a1", "goal": "g", "verdict": "passed", "model": "m", "fact": None, "ts": 1.0}])
    store.migrate_jsonl(str(jl))
    assert jl.exists()


def test_migrate_missing_file_returns_zero(store, tmp_path):
    assert store.migrate_jsonl(str(tmp_path / "nope.jsonl")) == 0


def test_migrate_default_path_uses_env(store, tmp_path, monkeypatch):
    jl = tmp_path / "env_memory.jsonl"
    _write_jsonl(jl, [{"id": "z9", "goal": "g", "verdict": "passed", "model": "m", "fact": None, "ts": 1.0}])
    monkeypatch.setenv("ARGOS_MEMORY_FILE", str(jl))
    assert store.migrate_jsonl(None) == 1


def test_migrate_env_path_expands_user_home(store, tmp_path, monkeypatch):
    """Internal documentation."""
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    jl = fake_home / "memory.jsonl"
    _write_jsonl(jl, [{"id": "h1", "goal": "g", "verdict": "passed", "model": "m", "fact": None, "ts": 1.0}])
    monkeypatch.setenv("HOME", str(fake_home))
    monkeypatch.setenv("ARGOS_MEMORY_FILE", "~/memory.jsonl")

    assert store.migrate_jsonl(None) == 1


def test_migrate_bad_ts_does_not_abort_migration(store, tmp_path):
    """Internal documentation."""
    jl = tmp_path / "memory.jsonl"
    jl.write_text(
        '{"id":"x","goal":"坏ts","verdict":"passed","model":"m","fact":null,"ts":"bad"}\n'
        '{"id":"y","goal":"好记录","verdict":"failed","model":"m","fact":null,"ts":2.0}\n',
        encoding="utf-8",
    )
    n = store.migrate_jsonl(str(jl))
    assert n == 2
    rows = store._con.execute(
        "SELECT id, ts FROM memory ORDER BY id"
    ).fetchall()
    by_id = {r["id"]: r["ts"] for r in rows}
    assert by_id["x"] == 0.0
    assert by_id["y"] == 2.0
