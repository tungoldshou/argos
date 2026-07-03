from __future__ import annotations

from pathlib import Path

from argos.daemon.store import RunStore


def test_append_assigns_monotonic_seq_to_all_nonmeta_events(tmp_path: Path):
    store = RunStore(tmp_path / "runs")
    assert store.append("r1", {"kind": "run_meta", "run_id": "r1"}) == 0
    s1 = store.append("r1", {"kind": "token_delta", "text": "a"})
    s2 = store.append("r1", {"kind": "state_change", "to": "running"})
    s3 = store.append("r1", {"kind": "code_action", "code": "x"})
    assert (s1, s2, s3) == (1, 2, 3)
    seqs = [e["_seq"] for e in store.replay("r1") if e["kind"] != "run_meta"]
    assert seqs == [1, 2, 3]


def test_replay_since_filters_by_seq_field_not_physical_row(tmp_path: Path):
    store = RunStore(tmp_path / "runs")
    store.append("r1", {"kind": "run_meta", "run_id": "r1"})
    store.append("r1", {"kind": "token_delta"})        # _seq=1
    store.append("r1", {"kind": "state_change"})        # _seq=2
    store.append("r1", {"kind": "code_action"})         # _seq=3
    got = list(store.replay("r1", since_seq=2))
    kinds = [e["kind"] for e in got]
    assert "run_meta" in kinds
    assert "token_delta" not in kinds
    assert "state_change" not in kinds
    assert "code_action" in kinds


def test_seq_monotonic_across_store_reinit(tmp_path: Path):
    store1 = RunStore(tmp_path / "runs")
    store1.append("r1", {"kind": "run_meta", "run_id": "r1"})
    store1.append("r1", {"kind": "token_delta"})   # _seq=1
    store1.append("r1", {"kind": "code_action"})   # _seq=2
    store2 = RunStore(tmp_path / "runs")
    assert store2.append("r1", {"kind": "token_delta"}) == 3


def test_full_replay_yields_legacy_events_without_seq(tmp_path: Path):
    store = RunStore(tmp_path / "runs")
    path = tmp_path / "runs" / "r1.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        '{"kind":"run_meta","run_id":"r1"}\n'
        '{"kind":"token_delta","text":"legacy"}\n'
        '{"kind":"state_change","to":"running"}\n',
        encoding="utf-8",
    )
    kinds = [e["kind"] for e in store.replay("r1")]
    assert kinds == ["run_meta", "token_delta", "state_change"]
