"""Internal documentation."""
from __future__ import annotations

import asyncio
import json
import time
import uuid
from pathlib import Path
from typing import Any, AsyncIterator

import pytest

from argos.conductor.orders import OrderStore, StandingOrder
from argos.conductor.proposals import ProactiveSuggestion
from argos.daemon.conductor_supervisor import (
    ConductorSupervisor,
    CONDUCTOR_RUN_ID,
    ensure_builtin_dream_order,
)
from argos.daemon.manager import RunManager
from argos.daemon.registry import RunRegistry
from argos.daemon.server import DaemonHTTPServer
from argos.daemon.worktree import WorktreeManager
from argos.protocol.events import (
    ProactiveSuggestionEvent,
    serialize_event,
    deserialize_event,
)



def _make_order(kind: str = "schedule", schedule: str = "09:00",
                trigger_glob: str | None = None, enabled: bool = True) -> StandingOrder:
    """Internal documentation."""
    return StandingOrder(
        id=uuid.uuid4().hex,
        utterance="测试常驻指令",
        kind=kind,
        schedule=schedule if kind == "schedule" else None,
        trigger_glob=trigger_glob if kind == "file_trigger" else None,
        goal_template="检查日志 {date}",
        enabled=enabled,
        created_at=time.time(),
        last_fired_at=None,
    )


def _make_suggestion(order_id: str = "order_x") -> ProactiveSuggestion:
    """Internal documentation."""
    return ProactiveSuggestion(
        id=uuid.uuid4().hex,
        order_id=order_id,
        goal="检查日志 2026-06-12",
        reason_human="定时触发（09:00）：测试常驻指令",
        suggested_at=time.time(),
        requires_confirmation=True,
    )


async def _raw_req(socket_path: Path, method: str, path: str, *,
                   session_id: str | None = None,
                   body: dict | None = None,
                   timeout: float = 10.0):
    from argos.daemon.client import DaemonClient
    cli = DaemonClient(socket_path, timeout=timeout)
    status, _headers, raw = await cli._request(
        method, path, session_id=session_id, body=body,
    )
    return status, raw


async def _create_session(socket_path: Path) -> str:
    status, raw = await _raw_req(socket_path, "POST", "/sessions")
    assert status == 201
    return json.loads(raw.decode())["session_id"]


async def _make_server_with_supervisor(
    tmp_path: Path,
    *,
    tick_interval: float = 999.0,
) -> tuple[DaemonHTTPServer, RunManager, ConductorSupervisor, Path]:
    """Internal documentation."""
    socket_path = tmp_path / "daemon.sock"
    runs_dir = tmp_path / "runs"
    orders_dir = tmp_path / "conductor"
    worktrees_dir = tmp_path / "worktrees"

    manager = RunManager(runs_dir=runs_dir, index_path=runs_dir / "index.json")
    registry = RunRegistry()
    worktree = WorktreeManager(base_dir=worktrees_dir)

    broadcast_events: list[dict] = []

    async def _broadcast(ev_dict: dict) -> None:
        broadcast_events.append(ev_dict)
        await manager.fanout(CONDUCTOR_RUN_ID, ev_dict)

    supervisor = ConductorSupervisor(
        orders_dir=orders_dir,
        tick_interval=tick_interval,
        broadcast_fn=_broadcast,
    )
    supervisor._broadcast_events = broadcast_events

    server = DaemonHTTPServer(
        manager=manager,
        socket_path=socket_path,
        registry=registry,
        worktree=worktree,
        conductor_supervisor=supervisor,
    )
    await server.start()
    return server, manager, supervisor, socket_path



@pytest.mark.asyncio
async def test_tick_emits_proactive_suggestion_event(tmp_path: Path):
    """Internal documentation."""
    server, manager, supervisor, socket_path = await _make_server_with_supervisor(tmp_path)
    try:
        s = _make_suggestion("ord_test")
        await supervisor._emit_suggestion(s)

        events_list = getattr(supervisor, "_broadcast_events", [])
        assert events_list, "广播列表不应为空"
        ev_dict = events_list[-1]
        assert ev_dict["kind"] == "proactive_suggestion"
        assert ev_dict["suggestion_id"] == s.id
        assert ev_dict["order_id"] == "ord_test"
        assert ev_dict["requires_confirmation"] is True
        assert ev_dict.get("run_id") == CONDUCTOR_RUN_ID
    finally:
        await server.stop()


@pytest.mark.asyncio
async def test_tick_stores_suggestion_in_pending(tmp_path: Path):
    """Internal documentation."""
    orders_dir = tmp_path / "conductor"
    events: list[dict] = []

    async def _bcast(ev: dict) -> None:
        events.append(ev)

    supervisor = ConductorSupervisor(
        orders_dir=orders_dir,
        tick_interval=999.0,
        broadcast_fn=_bcast,
    )
    s = _make_suggestion("ord_pending_test")
    supervisor._pending[s.id] = s
    await supervisor._emit_suggestion(s)

    assert s.id in supervisor.pending_suggestions
    assert supervisor.pending_suggestions[s.id].order_id == "ord_pending_test"



class _FakeCompletedLoop:
    """Internal documentation."""

    async def run(self, goal: str, session_id: str) -> AsyncIterator[dict]:
        yield {"kind": "token_delta", "text": "done"}


class _FakeLoopFactory:
    def __call__(self):
        return _FakeCompletedLoop()


@pytest.mark.asyncio
async def test_confirm_creates_run_with_worktree_and_l1_trust(tmp_path: Path):
    """Internal documentation."""
    server, manager, supervisor, socket_path = await _make_server_with_supervisor(tmp_path)
    server._loop_factory = _FakeLoopFactory()
    server._registry._max_concurrent = 5

    try:
        sid = await _create_session(socket_path)
        rec = server._sessions.get(sid)
        if rec is not None:
            import dataclasses
            server._sessions._sessions[sid] = dataclasses.replace(rec, role="owner")

        s = _make_suggestion("ord_confirm_test")
        supervisor._pending[s.id] = s

        status, raw = await _raw_req(
            socket_path, "POST", f"/suggestions/{s.id}/confirm",
            session_id=sid,
        )
        body = json.loads(raw.decode())

        assert status == 201, f"期望 201，实得 {status}：{body}"
        run_id = body.get("run_id")
        assert run_id, "response body 必须包含 run_id"
        assert body.get("isolation") == "worktree",\
            f"isolation 必须是 'worktree'（铁律），实得 {body.get('isolation')!r}"
        assert body.get("trust_level") == "L1_DANGEROUS_ONLY",\
            f"trust_level 必须是 'L1_DANGEROUS_ONLY'（铁律），实得 {body.get('trust_level')!r}"
        assert manager.get_run(run_id) is not None, "run 必须存在于 manager"
        assert s.id not in supervisor.pending_suggestions,\
            "confirm 后 suggestion 必须从 pending 移除"
    finally:
        await server.stop()


@pytest.mark.asyncio
async def test_confirm_worktree_path_returned(tmp_path: Path):
    """Internal documentation."""
    server, manager, supervisor, socket_path = await _make_server_with_supervisor(tmp_path)
    server._loop_factory = _FakeLoopFactory()
    server._registry._max_concurrent = 5

    try:
        sid = await _create_session(socket_path)
        rec = server._sessions.get(sid)
        if rec is not None:
            import dataclasses
            server._sessions._sessions[sid] = dataclasses.replace(rec, role="owner")

        s = _make_suggestion("ord_wt")
        supervisor._pending[s.id] = s

        status, raw = await _raw_req(
            socket_path, "POST", f"/suggestions/{s.id}/confirm",
            session_id=sid,
        )
        body = json.loads(raw.decode())
        assert status == 201
        assert "worktree_path" in body, "response body 必须包含 worktree_path 字段"
    finally:
        await server.stop()



@pytest.mark.asyncio
async def test_dismiss_then_confirm_returns_404(tmp_path: Path):
    """Internal documentation."""
    server, manager, supervisor, socket_path = await _make_server_with_supervisor(tmp_path)

    try:
        sid = await _create_session(socket_path)
        rec = server._sessions.get(sid)
        if rec is not None:
            import dataclasses
            server._sessions._sessions[sid] = dataclasses.replace(rec, role="owner")

        s = _make_suggestion("ord_dismiss")
        supervisor._pending[s.id] = s

        # dismiss
        status, raw = await _raw_req(
            socket_path, "POST", f"/suggestions/{s.id}/dismiss",
            session_id=sid,
        )
        body = json.loads(raw.decode())
        assert status == 200, f"dismiss 应返回 200，实得 {status}：{body}"
        assert body.get("state") == "dismissed"
        assert s.id not in supervisor.pending_suggestions

        status2, raw2 = await _raw_req(
            socket_path, "POST", f"/suggestions/{s.id}/confirm",
            session_id=sid,
        )
        body2 = json.loads(raw2.decode())
        assert status2 == 404, f"dismiss 后 confirm 应返回 404，实得 {status2}：{body2}"
    finally:
        await server.stop()



@pytest.mark.asyncio
async def test_create_order_missing_utterance_returns_400(tmp_path: Path):
    """Internal documentation."""
    server, manager, supervisor, socket_path = await _make_server_with_supervisor(tmp_path)
    try:
        sid = await _create_session(socket_path)
        rec = server._sessions.get(sid)
        if rec is not None:
            import dataclasses
            server._sessions._sessions[sid] = dataclasses.replace(rec, role="owner")

        status, raw = await _raw_req(
            socket_path, "POST", "/orders",
            session_id=sid,
            body={"kind": "schedule", "schedule": "09:00", "goal_template": "test"},
        )
        assert status == 400, f"期望 400，实得 {status}"
    finally:
        await server.stop()


@pytest.mark.asyncio
async def test_create_order_invalid_kind_returns_400(tmp_path: Path):
    """Internal documentation."""
    server, manager, supervisor, socket_path = await _make_server_with_supervisor(tmp_path)
    try:
        sid = await _create_session(socket_path)
        rec = server._sessions.get(sid)
        if rec is not None:
            import dataclasses
            server._sessions._sessions[sid] = dataclasses.replace(rec, role="owner")

        status, raw = await _raw_req(
            socket_path, "POST", "/orders",
            session_id=sid,
            body={"utterance": "test", "kind": "unknown_kind", "goal_template": "test"},
        )
        assert status == 400, f"期望 400，实得 {status}"
    finally:
        await server.stop()


@pytest.mark.asyncio
async def test_create_order_schedule_missing_schedule_returns_400(tmp_path: Path):
    """Internal documentation."""
    server, manager, supervisor, socket_path = await _make_server_with_supervisor(tmp_path)
    try:
        sid = await _create_session(socket_path)
        rec = server._sessions.get(sid)
        if rec is not None:
            import dataclasses
            server._sessions._sessions[sid] = dataclasses.replace(rec, role="owner")

        status, raw = await _raw_req(
            socket_path, "POST", "/orders",
            session_id=sid,
            body={"utterance": "test", "kind": "schedule", "goal_template": "test"},
        )
        assert status == 400
    finally:
        await server.stop()


@pytest.mark.asyncio
async def test_list_orders_empty(tmp_path: Path):
    """Internal documentation."""
    server, manager, supervisor, socket_path = await _make_server_with_supervisor(tmp_path)
    try:
        sid = await _create_session(socket_path)

        status, raw = await _raw_req(socket_path, "GET", "/orders", session_id=sid)
        assert status == 200
        orders = json.loads(raw.decode())
        assert isinstance(orders, list)
    finally:
        await server.stop()


@pytest.mark.asyncio
async def test_orders_crud_roundtrip(tmp_path: Path):
    """Internal documentation."""
    server, manager, supervisor, socket_path = await _make_server_with_supervisor(tmp_path)
    try:
        sid = await _create_session(socket_path)
        rec = server._sessions.get(sid)
        if rec is not None:
            import dataclasses
            server._sessions._sessions[sid] = dataclasses.replace(rec, role="owner")

        # CREATE
        status, raw = await _raw_req(
            socket_path, "POST", "/orders",
            session_id=sid,
            body={
                "utterance": "每天早上检查日志",
                "kind": "schedule",
                "schedule": "09:00",
                "goal_template": "检查日志 {date}",
            },
        )
        assert status == 201, f"create order 应返回 201，实得 {status}"
        created = json.loads(raw.decode())
        order_id = created.get("id")
        assert order_id, "response 必须包含 id"

        # LIST
        status, raw = await _raw_req(socket_path, "GET", "/orders", session_id=sid)
        assert status == 200
        orders = json.loads(raw.decode())
        ids = [o["id"] for o in orders]
        assert order_id in ids, f"新建 order {order_id} 应在列表中"

        # DELETE
        status, raw = await _raw_req(
            socket_path, "DELETE", f"/orders/{order_id}",
            session_id=sid,
        )
        assert status == 204, f"delete order 应返回 204，实得 {status}"

        # LIST after DELETE
        status, raw = await _raw_req(socket_path, "GET", "/orders", session_id=sid)
        assert status == 200
        orders_after = json.loads(raw.decode())
        assert order_id not in [o["id"] for o in orders_after],\
            "删除后 order_id 不应再出现在列表中"
    finally:
        await server.stop()


@pytest.mark.asyncio
async def test_delete_unknown_order_returns_404(tmp_path: Path):
    """Internal documentation."""
    server, manager, supervisor, socket_path = await _make_server_with_supervisor(tmp_path)
    try:
        sid = await _create_session(socket_path)
        rec = server._sessions.get(sid)
        if rec is not None:
            import dataclasses
            server._sessions._sessions[sid] = dataclasses.replace(rec, role="owner")

        status, raw = await _raw_req(
            socket_path, "DELETE", "/orders/nonexistent_id_12345",
            session_id=sid,
        )
        assert status == 404
    finally:
        await server.stop()



@pytest.mark.asyncio
async def test_conductor_supervisor_stop_clean(tmp_path: Path):
    """Internal documentation."""
    orders_dir = tmp_path / "conductor"
    events: list[dict] = []

    async def _bcast(ev: dict) -> None:
        events.append(ev)

    supervisor = ConductorSupervisor(
        orders_dir=orders_dir,
        tick_interval=0.05,
        broadcast_fn=_bcast,
    )
    supervisor.start()
    assert supervisor._task is not None
    assert not supervisor._task.done()

    await asyncio.sleep(0.1)

    await supervisor.stop()
    assert supervisor._task.done(), "task 应已完成（cancelled）"


@pytest.mark.asyncio
async def test_conductor_supervisor_double_stop(tmp_path: Path):
    """Internal documentation."""
    orders_dir = tmp_path / "conductor"

    async def _bcast(ev: dict) -> None:
        pass

    supervisor = ConductorSupervisor(
        orders_dir=orders_dir,
        tick_interval=0.05,
        broadcast_fn=_bcast,
    )
    supervisor.start()
    await supervisor.stop()
    await supervisor.stop()



@pytest.mark.asyncio
async def test_suggestion_never_auto_creates_run(tmp_path: Path):
    """Internal documentation."""
    orders_dir = tmp_path / "conductor"
    events: list[dict] = []
    run_count_before = [0]

    async def _bcast(ev: dict) -> None:
        events.append(ev)

    supervisor = ConductorSupervisor(
        orders_dir=orders_dir,
        tick_interval=999.0,
        broadcast_fn=_bcast,
    )

    s = _make_suggestion("ord_auto_run_check")
    supervisor._pending[s.id] = s
    await supervisor._emit_suggestion(s)

    assert len(supervisor.pending_suggestions) == 1,\
        "suggestion 应在 pending 中等待用户确认"
    assert not hasattr(supervisor, "_manager"),\
        "ConductorSupervisor 不应持有 manager 引用（安全边界：不能自己 create_run）"


@pytest.mark.asyncio
async def test_suggestions_list_endpoint(tmp_path: Path):
    """Internal documentation."""
    server, manager, supervisor, socket_path = await _make_server_with_supervisor(tmp_path)
    try:
        sid = await _create_session(socket_path)

        status, raw = await _raw_req(socket_path, "GET", "/suggestions", session_id=sid)
        assert status == 200
        assert json.loads(raw.decode()) == []

        s = _make_suggestion("ord_list")
        supervisor._pending[s.id] = s

        status, raw = await _raw_req(socket_path, "GET", "/suggestions", session_id=sid)
        assert status == 200
        suggestions = json.loads(raw.decode())
        assert len(suggestions) == 1
        assert suggestions[0]["suggestion_id"] == s.id
        assert suggestions[0]["requires_confirmation"] is True
    finally:
        await server.stop()



def test_proactive_suggestion_event_serialization():
    """ProactiveSuggestionEvent serialize → kind=proactive_suggestion。"""
    ev = ProactiveSuggestionEvent(
        suggestion_id="abc123def456",
        order_id="ord_golden",
        goal="检查昨天的日志",
        reason_human="定时触发（09:00）：每天早上整理日志",
        suggested_at=1700000000.0,
        requires_confirmation=True,
    )
    blob = serialize_event(ev)
    obj = json.loads(blob)
    assert obj["kind"] == "proactive_suggestion"
    assert obj["data"]["suggestion_id"] == "abc123def456"
    assert obj["data"]["order_id"] == "ord_golden"
    assert obj["data"]["requires_confirmation"] is True


def test_proactive_suggestion_event_roundtrip():
    """Internal documentation."""
    ev = ProactiveSuggestionEvent(
        suggestion_id="deadbeef0011",
        order_id="ord_rt",
        goal="整理日志",
        reason_human="文件变化触发（requirements.txt）",
        suggested_at=1700001234.5,
        requires_confirmation=True,
    )
    back = deserialize_event(serialize_event(ev))
    assert type(back) is ProactiveSuggestionEvent
    assert back.suggestion_id == ev.suggestion_id
    assert back.order_id == ev.order_id
    assert back.goal == ev.goal
    assert back.requires_confirmation is True


def test_proactive_suggestion_event_in_kind_to_class():
    """Internal documentation."""
    from argos.protocol.events import _KIND_TO_CLASS
    assert "proactive_suggestion" in _KIND_TO_CLASS


def test_proactive_suggestion_event_in_event_kind_literal():
    """Internal documentation."""
    from argos.protocol.events import EventKind
    assert "proactive_suggestion" in EventKind.__args__


def test_proactive_suggestion_event_requires_confirmation_invariant():
    """Internal documentation."""
    ev = ProactiveSuggestionEvent(
        suggestion_id="s1",
        order_id="o1",
        goal="g",
        reason_human="r",
        suggested_at=1.0,
        requires_confirmation=True,
    )
    obj = json.loads(serialize_event(ev))
    assert obj["data"]["requires_confirmation"] is True



def test_supervisor_dismiss_unknown_returns_false(tmp_path: Path):
    """Internal documentation."""
    async def _bcast(ev: dict) -> None:
        pass

    supervisor = ConductorSupervisor(
        orders_dir=tmp_path / "conductor",
        tick_interval=999.0,
        broadcast_fn=_bcast,
    )
    result = supervisor.dismiss_suggestion("nonexistent_id")
    assert result is False


def test_supervisor_get_and_pop_suggestion(tmp_path: Path):
    """Internal documentation."""
    async def _bcast(ev: dict) -> None:
        pass

    supervisor = ConductorSupervisor(
        orders_dir=tmp_path / "conductor",
        tick_interval=999.0,
        broadcast_fn=_bcast,
    )
    s = _make_suggestion("ord_pop_test")
    supervisor._pending[s.id] = s

    got = supervisor.get_suggestion(s.id)
    assert got is not None and got.id == s.id
    assert s.id in supervisor.pending_suggestions

    popped = supervisor.pop_suggestion(s.id)
    assert popped is not None and popped.id == s.id
    assert s.id not in supervisor.pending_suggestions

    assert supervisor.pop_suggestion(s.id) is None



@pytest.mark.asyncio
async def test_confirm_unknown_suggestion_returns_404(tmp_path: Path):
    """POST /suggestions/nonexistent/confirm → 404。"""
    server, manager, supervisor, socket_path = await _make_server_with_supervisor(tmp_path)
    try:
        sid = await _create_session(socket_path)
        rec = server._sessions.get(sid)
        if rec is not None:
            import dataclasses
            server._sessions._sessions[sid] = dataclasses.replace(rec, role="owner")

        status, raw = await _raw_req(
            socket_path, "POST", "/suggestions/nonexistent_id_xyz/confirm",
            session_id=sid,
        )
        assert status == 404
    finally:
        await server.stop()



@pytest.mark.asyncio
async def test_metadata_mode_confirm_does_not_leak_slots(tmp_path: Path):
    """Internal documentation."""
    server, manager, supervisor, socket_path = await _make_server_with_supervisor(tmp_path)
    try:
        sid = await _create_session(socket_path)
        rec = server._sessions.get(sid)
        if rec is not None:
            import dataclasses
            server._sessions._sessions[sid] = dataclasses.replace(rec, role="owner")

        n = server._registry.max_concurrent + 1
        for i in range(n):
            s = _make_suggestion(f"ord_slot_leak_{i}")
            supervisor._pending[s.id] = s
            status, raw = await _raw_req(
                socket_path, "POST", f"/suggestions/{s.id}/confirm", session_id=sid,
            )
            assert status == 201, (
                f"第 {i+1}/{n} 次 confirm 返 {status}(槽位泄漏回归!): {raw.decode()[:200]}"
            )
        assert server._registry.has_capacity(), "全部 confirm 完成后必须仍有空槽"
    finally:
        await server.stop()


@pytest.mark.asyncio
async def test_metadata_mode_create_run_does_not_leak_slots(tmp_path: Path):
    """Internal documentation."""
    server, manager, supervisor, socket_path = await _make_server_with_supervisor(tmp_path)
    try:
        sid = await _create_session(socket_path)
        n = server._registry.max_concurrent + 1
        for i in range(n):
            status, raw = await _raw_req(
                socket_path, "POST", "/runs", session_id=sid,
                body={"goal": f"slot leak probe {i}", "workspace": str(tmp_path)},
            )
            assert status == 201, (
                f"第 {i+1}/{n} 次 create_run 返 {status}(槽位泄漏回归!): {raw.decode()[:200]}"
            )
        assert server._registry.has_capacity()
    finally:
        await server.stop()


@pytest.mark.asyncio
async def test_confirm_shared_gate_l1_actually_applied(tmp_path: Path):
    """Internal documentation."""
    from argos.approval import ApprovalGate, ApprovalLevel
    from argos.permissions.trust_dial import TrustLevel

    server, manager, supervisor, socket_path = await _make_server_with_supervisor(tmp_path)
    server._loop_factory = _FakeLoopFactory()
    gate = ApprovalGate()
    gate.set_level(ApprovalLevel.AUTO)
    server._gate = gate
    try:
        sid = await _create_session(socket_path)
        rec = server._sessions.get(sid)
        if rec is not None:
            import dataclasses
            server._sessions._sessions[sid] = dataclasses.replace(rec, role="owner")

        s = _make_suggestion("ord_gate_l1")
        supervisor._pending[s.id] = s
        status, _ = await _raw_req(
            socket_path, "POST", f"/suggestions/{s.id}/confirm", session_id=sid,
        )
        assert status == 201
        assert gate.level == ApprovalLevel.CONFIRM, f"gate.level 应为 CONFIRM,实得 {gate.level}"
        assert getattr(gate, "_trust_level", None) == TrustLevel.L1_DANGEROUS_ONLY
    finally:
        await server.stop()



def test_builtin_dream_order_registered_idempotent(tmp_path: Path):
    """Internal documentation."""
    store = OrderStore(tmp_path / "conductor")
    ensure_builtin_dream_order(store)
    ensure_builtin_dream_order(store)

    orders = store.list()
    dream_orders = [o for o in orders if o.id == "builtin-dream-nightly"]
    assert len(dream_orders) == 1, f"应恰 1 条 builtin-dream-nightly,实得 {len(dream_orders)}"
    o = dream_orders[0]
    assert o.action == "dream"
    assert o.kind == "schedule"
    assert o.schedule == "03:00"
    assert o.goal_template == "__dream__"
    assert o.enabled is True


def test_dream_order_disabled_not_resurrected(tmp_path: Path):
    """Internal documentation."""
    store = OrderStore(tmp_path / "conductor")
    ensure_builtin_dream_order(store)

    order = store.get("builtin-dream-nightly")
    assert order is not None
    store.update(order.with_enabled(False))

    ensure_builtin_dream_order(store)
    after = store.get("builtin-dream-nightly")
    assert after is not None
    assert after.enabled is False, "disable 后 ensure 不应复活 builtin dream order"



def _make_dream_suggestion(order_id: str = "builtin-dream-nightly") -> ProactiveSuggestion:
    """Internal documentation."""
    return ProactiveSuggestion(
        id=uuid.uuid4().hex,
        order_id=order_id,
        goal="__dream__",
        reason_human="定时触发（03:00）：夜间整合",
        suggested_at=time.time(),
        requires_confirmation=True,
        action="dream",
    )


def test_material_gate_silences_empty_candidates(tmp_path: Path, monkeypatch):
    """Internal documentation."""
    from argos.learning import candidates as cand_mod

    cand_root = tmp_path / "candidates"
    monkeypatch.setattr(cand_mod, "DEFAULT_ROOT", cand_root)

    events: list[dict] = []

    async def _bcast(ev: dict) -> None:
        events.append(ev)

    supervisor = ConductorSupervisor(
        orders_dir=tmp_path / "conductor",
        tick_interval=999.0,
        broadcast_fn=_bcast,
    )

    s = _make_dream_suggestion()

    assert supervisor._should_emit_dream(s) is False, "空料应被材料门静默"

    from argos.learning.distiller import SkillCandidate
    cand = SkillCandidate(
        name="learned",
        body_markdown="# x\n\n```python\nprint('ok')\n```",
        verify_cmd="true",
        skill_md_path=Path("unused"),
    )
    p = cand_mod.save_candidate(
        cand, root=cand_root, source_run="run0001aaaa11",
        workspace=str(tmp_path), goal="fix bug",
    )
    assert p is not None
    assert supervisor._should_emit_dream(s) is True, "有料应放行"

    run_s = _make_suggestion("ord_run")
    assert supervisor._should_emit_dream(run_s) is True


def test_material_gate_import_failure_treated_as_no_material(tmp_path: Path, monkeypatch):
    """Internal documentation."""
    import builtins

    events: list[dict] = []

    async def _bcast(ev: dict) -> None:
        events.append(ev)

    supervisor = ConductorSupervisor(
        orders_dir=tmp_path / "conductor",
        tick_interval=999.0,
        broadcast_fn=_bcast,
    )

    real_import = builtins.__import__

    def _boom(name, *args, **kw):
        if "learning.dream" in name or name.endswith("dream"):
            raise ImportError("simulated learning module failure")
        return real_import(name, *args, **kw)

    monkeypatch.setattr(builtins, "__import__", _boom)
    s = _make_dream_suggestion()
    assert supervisor._should_emit_dream(s) is False



class _FakeDreamPipeline:
    """Internal documentation."""

    def __init__(self, *, is_running: bool = False, cross_busy: bool = False):
        self._is_running = is_running
        self._cross_busy = cross_busy
        self.run_called = False

    @property
    def is_running(self) -> bool:
        return self._is_running

    def cross_process_busy(self) -> bool:
        return self._cross_busy

    async def run(self):
        self.run_called = True
        from argos.learning.dream import DreamReport
        return DreamReport(units_total=1, promoted=1)


@pytest.mark.asyncio
async def test_confirm_dream_routes_to_pipeline_not_create_run(tmp_path: Path):
    """Internal documentation."""
    server, manager, supervisor, socket_path = await _make_server_with_supervisor(tmp_path)
    fake = _FakeDreamPipeline(is_running=False)
    server._dream_pipeline = fake

    create_run_calls = []
    real_create_run = manager.create_run

    async def _spy_create_run(*a, **kw):
        create_run_calls.append((a, kw))
        return await real_create_run(*a, **kw)

    manager.create_run = _spy_create_run

    try:
        sid = await _create_session(socket_path)
        rec = server._sessions.get(sid)
        if rec is not None:
            import dataclasses
            server._sessions._sessions[sid] = dataclasses.replace(rec, role="owner")

        s = _make_dream_suggestion()
        supervisor._pending[s.id] = s

        status, raw = await _raw_req(
            socket_path, "POST", f"/suggestions/{s.id}/confirm", session_id=sid,
        )
        body = json.loads(raw.decode())

        assert status == 202, f"dream confirm 期望 202,实得 {status}:{body}"
        assert body.get("state") == "dream_started"
        assert body.get("suggestion_id") == s.id
        await asyncio.sleep(0.05)
        assert fake.run_called, "fake pipeline.run 必须被调用"
        assert create_run_calls == [], "dream 路径绝不能 create_run"
        assert s.id not in supervisor.pending_suggestions
    finally:
        await server.stop()


@pytest.mark.asyncio
async def test_confirm_dream_busy_409(tmp_path: Path):
    """Internal documentation."""
    server, manager, supervisor, socket_path = await _make_server_with_supervisor(tmp_path)
    fake = _FakeDreamPipeline(is_running=True)
    server._dream_pipeline = fake

    try:
        sid = await _create_session(socket_path)
        rec = server._sessions.get(sid)
        if rec is not None:
            import dataclasses
            server._sessions._sessions[sid] = dataclasses.replace(rec, role="owner")

        s = _make_dream_suggestion()
        supervisor._pending[s.id] = s

        status, raw = await _raw_req(
            socket_path, "POST", f"/suggestions/{s.id}/confirm", session_id=sid,
        )
        assert status == 409, f"已在跑应返 409,实得 {status}:{raw.decode()[:200]}"
        assert not fake.run_called, "busy 时不应再调 run"
        assert s.id in supervisor.pending_suggestions
    finally:
        await server.stop()


@pytest.mark.asyncio
async def test_confirm_dream_cross_process_busy_409(tmp_path: Path):
    """Internal documentation."""
    server, manager, supervisor, socket_path = await _make_server_with_supervisor(tmp_path)
    fake = _FakeDreamPipeline(is_running=False, cross_busy=True)
    server._dream_pipeline = fake

    try:
        sid = await _create_session(socket_path)
        rec = server._sessions.get(sid)
        if rec is not None:
            import dataclasses
            server._sessions._sessions[sid] = dataclasses.replace(rec, role="owner")

        s = _make_dream_suggestion()
        supervisor._pending[s.id] = s

        status, raw = await _raw_req(
            socket_path, "POST", f"/suggestions/{s.id}/confirm", session_id=sid,
        )
        assert status == 409, (
            f"另一进程持锁应返 409,实得 {status}:{raw.decode()[:200]}"
        )
        await asyncio.sleep(0.02)
        assert not fake.run_called, "跨进程忙时绝不能派生 run(否则 202 却没真跑)"
        assert s.id in supervisor.pending_suggestions
    finally:
        await server.stop()


@pytest.mark.asyncio
async def test_confirm_dream_no_pipeline_503(tmp_path: Path):
    """Internal documentation."""
    server, manager, supervisor, socket_path = await _make_server_with_supervisor(tmp_path)

    try:
        sid = await _create_session(socket_path)
        rec = server._sessions.get(sid)
        if rec is not None:
            import dataclasses
            server._sessions._sessions[sid] = dataclasses.replace(rec, role="owner")

        s = _make_dream_suggestion()
        supervisor._pending[s.id] = s

        status, raw = await _raw_req(
            socket_path, "POST", f"/suggestions/{s.id}/confirm", session_id=sid,
        )
        assert status == 503, f"无 pipeline 应返 503,实得 {status}:{raw.decode()[:200]}"
    finally:
        await server.stop()



@pytest.mark.asyncio
async def test_dream_run_endpoint_starts_pipeline(tmp_path: Path):
    """Internal documentation."""
    server, manager, supervisor, socket_path = await _make_server_with_supervisor(tmp_path)
    fake = _FakeDreamPipeline(is_running=False)
    server._dream_pipeline = fake

    try:
        sid = await _create_session(socket_path)
        rec = server._sessions.get(sid)
        if rec is not None:
            import dataclasses
            server._sessions._sessions[sid] = dataclasses.replace(rec, role="owner")

        status, raw = await _raw_req(socket_path, "POST", "/dream/run", session_id=sid)
        body = json.loads(raw.decode())
        assert status == 202, f"期望 202,实得 {status}:{body}"
        assert body.get("state") == "dream_started"
        await asyncio.sleep(0.05)
        assert fake.run_called
    finally:
        await server.stop()


@pytest.mark.asyncio
async def test_dream_run_endpoint_busy_409(tmp_path: Path):
    """Internal documentation."""
    server, manager, supervisor, socket_path = await _make_server_with_supervisor(tmp_path)
    server._dream_pipeline = _FakeDreamPipeline(is_running=True)

    try:
        sid = await _create_session(socket_path)
        rec = server._sessions.get(sid)
        if rec is not None:
            import dataclasses
            server._sessions._sessions[sid] = dataclasses.replace(rec, role="owner")

        status, raw = await _raw_req(socket_path, "POST", "/dream/run", session_id=sid)
        assert status == 409
    finally:
        await server.stop()


@pytest.mark.asyncio
async def test_dream_report_endpoint_empty_and_nonempty(tmp_path: Path, monkeypatch):
    """Internal documentation."""
    dreams_dir = tmp_path / "dreams"
    monkeypatch.setenv("ARGOS_DREAMS_DIR", str(dreams_dir))

    server, manager, supervisor, socket_path = await _make_server_with_supervisor(tmp_path)
    try:
        sid = await _create_session(socket_path)
        rec = server._sessions.get(sid)
        if rec is not None:
            import dataclasses
            server._sessions._sessions[sid] = dataclasses.replace(rec, role="owner")

        status, raw = await _raw_req(socket_path, "GET", "/dream/report", session_id=sid)
        assert status == 200
        body = json.loads(raw.decode())
        assert body == {"report": None}, f"空态应返 {{'report': None}},实得 {body}"

        dreams_dir.mkdir(parents=True, exist_ok=True)
        report_line = {
            "ts": 1700000000.0, "units_total": 3, "promoted": 1,
            "rejected": 1, "skipped": 1, "memory_merged": 2, "memory_archived": 0,
        }
        (dreams_dir / "2026-06-13.jsonl").write_text(
            json.dumps(report_line, ensure_ascii=False) + "\n", encoding="utf-8",
        )

        status, raw = await _raw_req(socket_path, "GET", "/dream/report", session_id=sid)
        assert status == 200
        body = json.loads(raw.decode())
        assert body["report"] is not None
        assert body["report"]["units_total"] == 3
        assert body["report"]["promoted"] == 1
    finally:
        await server.stop()



@pytest.mark.asyncio
async def test_start_dream_concurrent_race_at_most_one_202(tmp_path: Path):
    """Internal documentation."""
    import asyncio

    server, manager, supervisor, socket_path = await _make_server_with_supervisor(tmp_path)

    run_count = 0

    class _SlowFakePipeline:
        """Internal documentation."""
        def __init__(self):
            self._is_running = False
            self.run_called = 0

        @property
        def is_running(self) -> bool:
            return self._is_running

        def cross_process_busy(self) -> bool:
            return False

        async def run(self):
            nonlocal run_count
            run_count += 1
            self.run_called += 1
            self._is_running = True
            await asyncio.sleep(0.02)
            self._is_running = False
            from argos.learning.dream import DreamReport
            return DreamReport(units_total=1, promoted=1)

    fake = _SlowFakePipeline()
    server._dream_pipeline = fake

    try:
        sid = await _create_session(socket_path)
        rec = server._sessions.get(sid)
        if rec is not None:
            import dataclasses
            server._sessions._sessions[sid] = dataclasses.replace(rec, role="owner")

        results = await asyncio.gather(
            _raw_req(socket_path, "POST", "/dream/run", session_id=sid),
            _raw_req(socket_path, "POST", "/dream/run", session_id=sid),
        )

        statuses = [r[0] for r in results]
        bodies = [json.loads(r[1].decode()) for r in results]

        count_202 = statuses.count(202)
        count_409 = statuses.count(409)

        assert count_202 == 1, (
            f"并发两请求应恰好只有一个 202，实得 {statuses}。"
            f"如果两个都是 202，说明 TOCTOU 守卫失效（_dream_starting 未置位）。"
        )
        assert count_409 == 1, (
            f"另一个请求应返 409 dream_busy，实得 {statuses}。bodies={bodies}"
        )

        await asyncio.sleep(0.05)

        assert fake.run_called == 1, (
            f"pipeline.run 应只被调一次，实际调了 {fake.run_called} 次"
        )
    finally:
        await server.stop()
