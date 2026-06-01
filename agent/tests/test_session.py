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
    st1 = server._get_or_create_session(None, verify_cmd="pytest", project_dir=None, guard=None)
    # 第二轮传不同 verify_cmd → 被忽略,沿用首轮锁定值
    st2 = server._get_or_create_session(st1.session_id, verify_cmd="tsc", project_dir=None, guard=None)
    assert st2 is st1
    assert st2.verify_cmd == "pytest"


def test_session_lru_cap():
    server.SESSIONS.clear()
    ids = [server._get_or_create_session(None, None, None, None).session_id for _ in range(server.MAX_SESSIONS + 5)]
    assert len(server.SESSIONS) <= server.MAX_SESSIONS
    # 最新的仍在
    assert ids[-1] in server.SESSIONS
