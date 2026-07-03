import threading

import pytest

from argos.memory.store import ArgosStore, _CHECKPOINT_EVERY


def test_concurrent_writes_all_persist(tmp_path):
    path = str(tmp_path / "argos.db")
    store = ArgosStore(db_path=path)
    sid = store.create_session(title="t", model="m", system_snapshot="s")

    errors: list[Exception] = []

    def writer(n: int) -> None:
        try:
            s = ArgosStore(db_path=path)
            for i in range(10):
                s.append_message(sid, role="user", content=f"t{n}-{i}")
            s.close()
        except Exception as e:  # noqa: BLE001
            errors.append(e)

    threads = [threading.Thread(target=writer, args=(n,)) for n in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert errors == [], f"并发写报错(重试未兜住):{errors}"
    cnt = store._con.execute(
        "SELECT count(*) FROM messages WHERE session_id=?", (sid,)
    ).fetchone()[0]
    assert cnt == 40
    store.close()


def test_checkpoint_triggers_every_50_writes(tmp_path):
    checkpoint_hits: list[int] = []

    class TrackingStore(ArgosStore):
        def _write(self, sql: str, params: tuple = ()):
            before = self._writes
            cur = super()._write(sql, params)
            if before // _CHECKPOINT_EVERY != self._writes // _CHECKPOINT_EVERY:
                checkpoint_hits.append(self._writes)
            return cur

        def _write_txn(self, statements):
            before = self._writes
            super()._write_txn(statements)
            if before // _CHECKPOINT_EVERY != self._writes // _CHECKPOINT_EVERY:
                checkpoint_hits.append(self._writes)

    store = TrackingStore(db_path=str(tmp_path / "argos.db"))
    sid = store.create_session(title="t", model="m", system_snapshot="s")
    for _ in range(_CHECKPOINT_EVERY):
        store.append_message(sid, role="user", content="x")
    assert len(checkpoint_hits) >= 1, (
        f"_CHECKPOINT_EVERY={_CHECKPOINT_EVERY} 写完后应触发至少 1 次 PASSIVE checkpoint，"
        f"实际 _writes={store._writes}，checkpoint_hits={checkpoint_hits}"
    )
    row = store._con.execute("PRAGMA wal_checkpoint(PASSIVE)").fetchone()
    assert row is not None
    store.close()
