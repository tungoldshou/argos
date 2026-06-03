"""Phase 2:写抖动重试 + 50 写 checkpoint(spec §5.2)。"""
import threading

import pytest

from argos_agent.memory.store import ArgosStore, _CHECKPOINT_EVERY


def test_concurrent_writes_all_persist(tmp_path):
    path = str(tmp_path / "argos.db")
    store = ArgosStore(db_path=path)
    sid = store.create_session(title="t", model="m", system_snapshot="s")

    errors: list[Exception] = []

    def writer(n: int) -> None:
        try:
            # 各线程用独立 store 实例(独立连接)撞同一文件,触发 WAL 写锁竞争
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
    assert cnt == 40  # 4 线程 × 10 条全部落盘
    store.close()


def test_checkpoint_triggers_every_50_writes(tmp_path):
    """验证写计数每跨过 50 触发一次 PASSIVE checkpoint。

    sqlite3.Connection.execute 是只读 C 扩展属性，无法 monkeypatch。
    改为 subclass ArgosStore，覆写 _write 与 _write_txn（append_message 走批量事务，M-4），
    在父类完成写后检查 checkpoint 分支是否命中（_writes 跨过 _CHECKPOINT_EVERY 的倍数）。
    """
    checkpoint_hits: list[int] = []

    class TrackingStore(ArgosStore):
        """覆写两条写路径：父类完成写（含 checkpoint）后，若本次跨过 N*50，记录下来。"""
        def _write(self, sql: str, params: tuple = ()):
            before = self._writes
            cur = super()._write(sql, params)
            # 单写自增 1：若新计数命中 %50==0 说明 checkpoint 分支已触发
            if before // _CHECKPOINT_EVERY != self._writes // _CHECKPOINT_EVERY:
                checkpoint_hits.append(self._writes)
            return cur

        def _write_txn(self, statements):
            before = self._writes
            super()._write_txn(statements)
            # 批量写跨过 _CHECKPOINT_EVERY 的倍数 → 父类已做 checkpoint
            if before // _CHECKPOINT_EVERY != self._writes // _CHECKPOINT_EVERY:
                checkpoint_hits.append(self._writes)

    store = TrackingStore(db_path=str(tmp_path / "argos.db"))
    sid = store.create_session(title="t", model="m", system_snapshot="s")  # 1 写
    # append_message = 2 写/笔(messages + fts 同事务)，写到跨过 50 的倍数
    for _ in range(_CHECKPOINT_EVERY):
        store.append_message(sid, role="user", content="x")
    # _writes 应超过 50（1 + 50*2 = 101），至少一次跨过 50 的倍数
    assert len(checkpoint_hits) >= 1, (
        f"_CHECKPOINT_EVERY={_CHECKPOINT_EVERY} 写完后应触发至少 1 次 PASSIVE checkpoint，"
        f"实际 _writes={store._writes}，checkpoint_hits={checkpoint_hits}"
    )
    # 验证 WAL checkpoint 真的可执行：执行一次 PASSIVE 拿到 (busy, log, checkpointed)
    row = store._con.execute("PRAGMA wal_checkpoint(PASSIVE)").fetchone()
    assert row is not None
    store.close()
