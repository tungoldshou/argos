"""Phase 2:events 持久化 + replay 重建(契约 §2 / spec §5.8 + §12.6)。"""
import pytest

from argos_agent.memory.store import ArgosStore, ReplayState
from argos_agent.tui import events as E


@pytest.fixture
def store(tmp_path):
    s = ArgosStore(db_path=str(tmp_path / "argos.db"))
    yield s
    s.close()


def test_append_event_persists_serialized(store):
    sid = store.create_session(title="t", model="m", system_snapshot="s")
    store.append_event(sid, E.TokenDelta(text="增量文本"))
    row = store._con.execute(
        "SELECT kind, blob FROM events WHERE session_id=?", (sid,)
    ).fetchone()
    assert row["kind"] == "token_delta"
    assert "增量文本" in row["blob"]


def test_replay_reconstructs_messages_and_events(store):
    sid = store.create_session(title="续跑任务", model="m", system_snapshot="s")
    store.append_message(sid, role="user", content="goal")
    store.append_event(sid, E.PhaseChange(phase="plan", actions=0))
    store.append_event(sid, E.CodeAction(code="print(1)", step=0))
    store.append_event(sid, E.PhaseChange(phase="act", actions=1))

    rs = store.replay(sid)
    assert isinstance(rs, ReplayState)
    assert rs.session.session_id == sid
    assert len(rs.messages) == 1 and rs.messages[0].content == "goal"
    assert len(rs.events) == 3
    assert isinstance(rs.events[1], E.CodeAction)
    # last_phase = 最后一个 PhaseChange 的 phase
    assert rs.last_phase == "act"


def test_replay_last_phase_defaults_plan_when_no_phasechange(store):
    sid = store.create_session(title="t", model="m", system_snapshot="s")
    store.append_event(sid, E.TokenDelta(text="x"))
    rs = store.replay(sid)
    assert rs.last_phase == "plan"


def test_replay_missing_session_raises(store):
    with pytest.raises(KeyError):
        store.replay("nope00000000")


def test_events_ordered_by_insertion(store):
    sid = store.create_session(title="t", model="m", system_snapshot="s")
    for i in range(5):
        store.append_event(sid, E.CodeAction(code=f"step{i}", step=i))
    rs = store.replay(sid)
    assert [e.step for e in rs.events] == [0, 1, 2, 3, 4]
