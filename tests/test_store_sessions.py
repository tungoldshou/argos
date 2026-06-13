"""Phase 2:sessions + messages 读写(契约 §2)。"""
import pytest

from argos.memory.store import ArgosStore, SessionRow, MessageRow


@pytest.fixture
def store(tmp_path):
    s = ArgosStore(db_path=str(tmp_path / "argos.db"))
    yield s
    s.close()


def test_create_session_returns_12_hex_id(store):
    sid = store.create_session(title="跑测试", model="MiniMax-M2", system_snapshot="SYS")
    assert isinstance(sid, str) and len(sid) == 12
    int(sid, 16)  # 合法 hex


def test_get_session_roundtrip(store):
    sid = store.create_session(title="t", model="m", system_snapshot="s", parent="p123")
    row = store.get_session(sid)
    assert isinstance(row, SessionRow)
    assert row.session_id == sid
    assert row.title == "t" and row.model == "m" and row.parent == "p123"
    assert row.tokens_in == 0 and row.cost_usd == 0.0
    assert row.ended_at is None and row.started_at > 0


def test_get_session_missing_returns_none(store):
    assert store.get_session("deadbeef0000") is None


def test_append_message_returns_id_and_persists(store):
    sid = store.create_session(title="t", model="m", system_snapshot="s")
    mid = store.append_message(sid, role="user", content="修复登录失败", token_count=5)
    assert isinstance(mid, str) and len(mid) == 12
    rows = store._con.execute(
        "SELECT role, content, token_count FROM messages WHERE message_id=?", (mid,)
    ).fetchone()
    assert rows["role"] == "user" and rows["content"] == "修复登录失败" and rows["token_count"] == 5


def test_append_message_also_indexes_fts(store):
    sid = store.create_session(title="t", model="m", system_snapshot="s")
    store.append_message(sid, role="user", content="hello trigram world")
    cnt = store._con.execute(
        "SELECT count(*) FROM messages_fts WHERE messages_fts MATCH 'trigram'"
    ).fetchone()[0]
    assert cnt == 1


def test_list_sessions_desc_by_started(store):
    a = store.create_session(title="a", model="m", system_snapshot="s")
    b = store.create_session(title="b", model="m", system_snapshot="s")
    rows = store.list_sessions(limit=10)
    assert [r.session_id for r in rows][:2] == [b, a]  # 最新在前


def test_list_sessions_respects_limit(store):
    for i in range(5):
        store.create_session(title=str(i), model="m", system_snapshot="s")
    assert len(store.list_sessions(limit=3)) == 3
