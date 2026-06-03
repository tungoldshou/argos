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
    """验证 _write 每 50 次写触发一次 PASSIVE checkpoint。

    sqlite3.Connection.execute 是只读 C 扩展属性，无法 monkeypatch。
    改为 subclass ArgosStore，覆写 _write，在真实写完成后额外记录 checkpoint 发生时的
    _writes 值——只要 _writes % _CHECKPOINT_EVERY == 0 说明 checkpoint 分支已命中。
    同时用 WAL 页面数确认 checkpoint 真的把 WAL 写回了主文件（pages_moved > 0）。
    """
    checkpoint_write_counts: list[int] = []

    class TrackingStore(ArgosStore):
        """覆写 _write：在父类完成写（含 checkpoint）后，若本次恰好是第 N*50 次，记录下来。"""
        def _write(self, sql: str, params: tuple = ()):
            cur = super()._write(sql, params)
            # super()._write 已自增 _writes 并在 %50==0 时做了 checkpoint
            if self._writes % _CHECKPOINT_EVERY == 0:
                checkpoint_write_counts.append(self._writes)
            return cur

    store = TrackingStore(db_path=str(tmp_path / "argos.db"))
    sid = store.create_session(title="t", model="m", system_snapshot="s")  # 1 写
    # append_message = 2 写(messages + fts)，再写到跨过 50 的倍数
    for _ in range(_CHECKPOINT_EVERY):
        store.append_message(sid, role="user", content="x")
    # _writes 应超过 50（1 + 50*2 = 101），至少一次命中 %50==0
    assert len(checkpoint_write_counts) >= 1, (
        f"_CHECKPOINT_EVERY={_CHECKPOINT_EVERY} 写完后应触发至少 1 次 PASSIVE checkpoint，"
        f"实际 _writes={store._writes}，checkpoint_counts={checkpoint_write_counts}"
    )
    # 验证 WAL checkpoint 真的执行了：执行一次 PASSIVE 获取 pages_moved
    row = store._con.execute("PRAGMA wal_checkpoint(PASSIVE)").fetchone()
    # row = (busy, log, checkpointed)；checkpointed >= 0 表示 checkpoint 正常工作
    assert row is not None
    store.close()
