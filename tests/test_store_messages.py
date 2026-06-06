# tests/test_store_messages.py
from argos_agent.memory.store import ArgosStore


def test_get_messages_returns_thread_in_order(tmp_path):
    store = ArgosStore(db_path=str(tmp_path / "a.db"))
    store.ensure_session("s1", title="t", model="worker", system_snapshot="")
    store.append_message("s1", role="user", content="第一轮目标")
    store.append_message("s1", role="assistant", content="第一轮回答")
    store.append_message("s1", role="user", content="第二轮:继续")
    msgs = store.get_messages("s1")
    assert [m["role"] for m in msgs] == ["user", "assistant", "user"]
    assert msgs[0]["content"] == "第一轮目标"
    assert msgs[-1]["content"] == "第二轮:继续"
    # 跨 session 隔离
    store.ensure_session("s2", title="t", model="worker", system_snapshot="")
    assert store.get_messages("s2") == []
    store.close()
