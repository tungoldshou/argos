"""Internal documentation."""
from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path

import pytest

from argos.daemon.events import RunCheckpoint, RunFailure, RunMeta
from argos.daemon.index import StateIndex
from argos.daemon.state_machine import (
    ALLOWED, RUN_ID_RE, STATES, TERMINAL_STATES, InvalidTransition,
    read_state, transition,
)
from argos.daemon.store import RunStore


def _meta(run_id: str = "abc123def456") -> RunMeta:
    return RunMeta(
        run_id=run_id, goal="x", workspace="/x", model="m",
        created_at=time.time(), approval_level="confirm",
    )


# ── RunStore:JSONL append / replay / corruption recovery ───────────────────

def test_runstore_append_then_replay(tmp_path: Path):
    """Internal documentation."""
    store = RunStore(tmp_path)
    run_id = "abc123def456"
    store.append(run_id, _meta(run_id).to_dict())
    rows = list(store.replay(run_id))
    assert len(rows) == 1
    assert rows[0]["run_id"] == run_id
    assert rows[0]["kind"] == "run_meta"


def test_runstore_replay_skips_corrupt_lines(tmp_path: Path):
    """Internal documentation."""
    store = RunStore(tmp_path)
    run_id = "abc123def456"
    store.append(run_id, _meta(run_id).to_dict())
    path = store._path_for(run_id)
    with path.open("a", encoding="utf-8") as f:
        f.write("{not valid json\n")
    store.append(run_id, {"kind": "state_change", "to": "running"})
    rows = list(store.replay(run_id))
    assert len(rows) == 2
    assert rows[0]["kind"] == "run_meta"
    assert rows[1]["to"] == "running"


def test_runstore_empty_file_yields_nothing(tmp_path: Path):
    """Internal documentation."""
    store = RunStore(tmp_path)
    rows = list(store.replay("nonexistent"))
    assert rows == []


def test_runstore_replay_since_seq(tmp_path: Path):
    """Internal documentation."""
    store = RunStore(tmp_path)
    run_id = "abc123def456"
    store.append(run_id, _meta(run_id).to_dict())
    for i in range(5):
        store.append(run_id, {"kind": "token_delta", "text": f"hello {i}"})
    rows = list(store.replay(run_id, since_seq=3))
    assert len(rows) == 1 + 2


def test_runstore_concurrent_appends(tmp_path: Path):
    """Internal documentation."""
    async def _go():
        store = RunStore(tmp_path)
        run_id = "abc123def456"
        store.append(run_id, _meta(run_id).to_dict())
        async def write_one(i: int):
            store.append(run_id, {"kind": "token_delta", "text": f"t{i}"})

        await asyncio.gather(*(write_one(i) for i in range(50)))
        return list(store.replay(run_id))

    rows = asyncio.run(_go())
    assert len(rows) == 1 + 50


def test_runstore_creates_runs_dir(tmp_path: Path):
    """Internal documentation."""
    runs = tmp_path / "fresh" / "runs"
    store = RunStore(runs)
    run_id = "abc123def456"
    store.append(run_id, _meta(run_id).to_dict())
    assert (runs / f"{run_id}.jsonl").exists()


def test_runstore_corruption_first_line_not_meta(tmp_path: Path):
    """Internal documentation."""
    store = RunStore(tmp_path)
    run_id = "abc123def456"
    (store._path_for(run_id)).write_text(
        json.dumps({"kind": "token_delta", "text": "x"}) + "\n",
        encoding="utf-8",
    )
    with pytest.raises(Exception):  # CorruptionError
        list(store.replay(run_id))


def test_runstore_rejects_virtual_underscore_streams(tmp_path: Path):
    """Internal documentation."""
    store = RunStore(tmp_path)
    with pytest.raises(ValueError, match="virtual"):
        store.append("_conductor", {"kind": "proactive_suggestion", "goal": "x"})
    assert not (store._path_for("_conductor")).exists()


def test_runstore_list_runs(tmp_path: Path):
    """Internal documentation."""
    store = RunStore(tmp_path)
    store.append("aaa111bbb222", _meta("aaa111bbb222").to_dict())
    store.append("ccc333ddd444", _meta("ccc333ddd444").to_dict())
    runs = store.list_runs()
    assert set(runs) == {"aaa111bbb222", "ccc333ddd444"}


def test_runstore_last_state(tmp_path: Path):
    """Internal documentation."""
    store = RunStore(tmp_path)
    run_id = "abc123def456"
    store.append(run_id, _meta(run_id).to_dict())
    assert store.last_state(run_id) is None
    store.append(run_id, {"kind": "state_change", "to": "running", "from": "pending"})
    assert store.last_state(run_id) == "running"
    store.append(run_id, {"kind": "state_change", "to": "paused", "from": "running"})
    assert store.last_state(run_id) == "paused"



def test_stateindex_upsert_roundtrip(tmp_path: Path):
    """Internal documentation."""
    index = StateIndex(tmp_path / "index.json")
    index.upsert("abc", state="running", goal="x", workspace="/x", created_at=1.0,
                 updated_at=1.0, last_event_seq=0)
    assert index.get("abc").state == "running"
    index.save()
    index2 = StateIndex(tmp_path / "index.json")
    index2.load()
    assert index2.get("abc").state == "running"


def test_stateindex_atomic_write_no_partial(tmp_path: Path):
    """Internal documentation."""
    index = StateIndex(tmp_path / "index.json")
    index.upsert("abc", state="running", goal="x", workspace="/x", created_at=1.0,
                 updated_at=1.0, last_event_seq=0)
    index.save()
    import os
    real_replace = os.replace

    def _boom(src, dst):
        raise OSError("disk full")

    os.replace = _boom
    try:
        index.upsert("abc", state="paused", updated_at=2.0, last_event_seq=5)
        with pytest.raises(OSError):
            index.save()
    finally:
        os.replace = real_replace
    fresh = StateIndex(tmp_path / "index.json")
    fresh.load()
    assert fresh.get("abc").state == "running"


def test_stateindex_missing_file_empty(tmp_path: Path):
    """Internal documentation."""
    index = StateIndex(tmp_path / "missing.json")
    index.load()
    assert index.get("abc") is None
    assert index.list() == []


def test_stateindex_corrupt_json_handled(tmp_path: Path):
    """Internal documentation."""
    p = tmp_path / "index.json"
    p.write_text("{not valid json", encoding="utf-8")
    index = StateIndex(p)
    index.load()
    assert index.list() == []


def test_stateindex_remove(tmp_path: Path):
    """Internal documentation."""
    index = StateIndex(tmp_path / "index.json")
    index.upsert("a", state="running", goal="", workspace="", created_at=1.0)
    index.upsert("b", state="pending", goal="", workspace="", created_at=1.0)
    index.remove("a")
    assert index.get("a") is None
    assert index.get("b") is not None


def test_stateindex_upsert_preserves_unspecified_fields(tmp_path: Path):
    """Internal documentation."""
    index = StateIndex(tmp_path / "index.json")
    index.upsert("a", state="running", goal="g1", workspace="/w", model="m1",
                 created_at=1.0, updated_at=1.0)
    index.upsert("a", state="paused")
    e = index.get("a")
    assert e.state == "paused"
    assert e.goal == "g1"
    assert e.workspace == "/w"
    assert e.model == "m1"



def test_state_machine_all_states_in_allowed():
    """Internal documentation."""
    expected = {"pending", "running", "paused", "suspended",
                "completed", "failed", "cancelled"}
    assert set(ALLOWED.keys()) == expected
    assert expected == STATES


def test_state_machine_terminal_states():
    """Internal documentation."""
    assert TERMINAL_STATES == frozenset({"completed", "failed", "cancelled"})
    for s in ("completed", "failed", "cancelled"):
        assert ALLOWED[s] == set()


def test_state_machine_legal_transition():
    """Internal documentation."""
    assert "paused" in ALLOWED["running"]


def test_state_machine_illegal_transition_raises(tmp_path: Path):
    """Internal documentation."""
    index = StateIndex(tmp_path / "index.json")
    with pytest.raises(InvalidTransition, match=r"running.*pending"):
        transition(current="running", target="pending", index=index, run_id="abc",
                   store=None, reason="test")


def _mk_index(path):
    """Internal documentation."""
    return StateIndex(path / "i.json")


def test_state_machine_terminal_write_protected(tmp_path: Path):
    """Internal documentation."""
    index = StateIndex(tmp_path / "index.json")
    index.upsert("abc", state="completed", goal="x", workspace="/x", created_at=1.0,
                 updated_at=1.0, last_event_seq=0)
    index.save()
    store = RunStore(tmp_path / "runs")
    transition(current="completed", target="cancelled", index=index, run_id="abc",
               store=store, reason="test")
    assert index.get("abc").state == "completed"


def test_state_machine_dynamic_from_state(tmp_path: Path):
    """Internal documentation."""
    index = StateIndex(tmp_path / "index.json")
    index.upsert("abc", state="paused", goal="x", workspace="/x", created_at=1.0,
                 updated_at=1.0, last_event_seq=0)
    index.save()
    store = RunStore(tmp_path / "runs")
    transition(current=None, target="running", index=index, run_id="abc",
               store=store, reason="user_resume")
    assert index.get("abc").state == "running"


def test_read_state_from_index(tmp_path: Path):
    """Internal documentation."""
    index = StateIndex(tmp_path / "index.json")
    index.upsert("abc", state="running", goal="x", workspace="/x", created_at=1.0,
                 updated_at=1.0, last_event_seq=0)
    index.save()
    assert read_state("abc", index) == "running"
    assert read_state("nonexistent", index) == "pending"


def test_run_id_regex():
    """Internal documentation."""
    assert RUN_ID_RE.match("abc123def456")
    assert RUN_ID_RE.match("0123456789ab")
    assert not RUN_ID_RE.match("abc")
    assert not RUN_ID_RE.match("abc123def4567")
    assert not RUN_ID_RE.match("xyz123def456")
