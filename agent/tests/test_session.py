"""多轮会话状态测试:session 历史累积,verify/project 首轮锁定。"""
from argos_agent import server


def test_new_session_creates_state():
    server.SESSIONS.clear()
    st = server._get_or_create_session(None, verify_cmd="pytest", project_dir=None, guard=None)
    assert st.session_id
    assert st.verify_cmd == "pytest"
    assert st.messages == []
    assert st.session_id in server.SESSIONS


def test_existing_session_locks_setup():
    server.SESSIONS.clear()
    st1 = server._get_or_create_session(None, verify_cmd="pytest", project_dir="/a", guard=["t.py"])
    # 第二轮传不同 setup → 全部被忽略,沿用首轮锁定值
    st2 = server._get_or_create_session(st1.session_id, verify_cmd="tsc", project_dir="/b", guard=["x.py"])
    assert st2 is st1
    assert st2.verify_cmd == "pytest"
    assert st2.project_dir == "/a"
    assert st2.guard == ["t.py"]


def test_session_lru_cap():
    server.SESSIONS.clear()
    ids = [server._get_or_create_session(None, None, None, None).session_id for _ in range(server.MAX_SESSIONS + 5)]
    assert len(server.SESSIONS) <= server.MAX_SESSIONS
    # 最新的仍在
    assert ids[-1] in server.SESSIONS
    # 最旧的已被淘汰
    assert ids[0] not in server.SESSIONS


def test_lru_recency_survival():
    server.SESSIONS.clear()
    ids = [server._get_or_create_session(None, None, None, None).session_id for _ in range(server.MAX_SESSIONS)]
    first_id = ids[0]
    never_touched = ids[1]  # 早期但从未再被触碰
    # 重新触碰最旧的 → 它变成最近使用
    server._get_or_create_session(first_id, None, None, None)
    # 再建 3 个新会话 → 触发淘汰最旧(应是 never_touched 而非 first_id)
    for _ in range(3):
        server._get_or_create_session(None, None, None, None)
    assert first_id in server.SESSIONS
    assert never_touched not in server.SESSIONS
