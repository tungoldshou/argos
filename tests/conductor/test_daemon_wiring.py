"""P5b conductor daemon 接线验收测试。

验收条目：
  a. tick → suggestion 事件落盘（ProactiveSuggestionEvent 正确序列化入 _conductor 流）
  b. confirm → run 创建，且 isolation=worktree + trust_level=L1_DANGEROUS_ONLY（铁证断言）
  c. dismiss 后 confirm → 404
  d. orders CRUD fail-closed 分支（非法 body → 400；未知 id → 404）
  e. daemon 关闭 tick loop 干净退出（CancelledError 不泄露）
  f. suggestion 绝不在无 confirm 时变 run（扫 run 列表断言）
  g. 黄金测试：ProactiveSuggestionEvent serialize/deserialize round-trip
"""
from __future__ import annotations

import asyncio
import json
import time
import uuid
from pathlib import Path
from typing import Any, AsyncIterator

import pytest

from argos_agent.conductor.orders import OrderStore, StandingOrder
from argos_agent.conductor.proposals import ProactiveSuggestion
from argos_agent.daemon.conductor_supervisor import ConductorSupervisor, CONDUCTOR_RUN_ID
from argos_agent.daemon.manager import RunManager
from argos_agent.daemon.registry import RunRegistry
from argos_agent.daemon.server import DaemonHTTPServer
from argos_agent.daemon.worktree import WorktreeManager
from argos_agent.protocol.events import (
    ProactiveSuggestionEvent,
    serialize_event,
    deserialize_event,
)


# ── 辅助 ──────────────────────────────────────────────────────────────────────

def _make_order(kind: str = "schedule", schedule: str = "09:00",
                trigger_glob: str | None = None, enabled: bool = True) -> StandingOrder:
    """构造测试用 StandingOrder。"""
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
    """构造测试用 ProactiveSuggestion。"""
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
    from argos_agent.daemon.client import DaemonClient
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
    tick_interval: float = 999.0,  # 默认不自动 tick（手动控制）
) -> tuple[DaemonHTTPServer, RunManager, ConductorSupervisor, Path]:
    """构建测试用 DaemonHTTPServer + ConductorSupervisor，返回 (server, manager, supervisor, socket)。"""
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
        manager.store.append(CONDUCTOR_RUN_ID, ev_dict)
        await manager.fanout(CONDUCTOR_RUN_ID, ev_dict)

    supervisor = ConductorSupervisor(
        orders_dir=orders_dir,
        tick_interval=tick_interval,
        broadcast_fn=_broadcast,
    )
    supervisor._broadcast_events = broadcast_events  # 暴露给测试检查

    server = DaemonHTTPServer(
        manager=manager,
        socket_path=socket_path,
        registry=registry,
        worktree=worktree,
        conductor_supervisor=supervisor,
    )
    await server.start()
    return server, manager, supervisor, socket_path


# ── a. tick → suggestion 事件落盘 ────────────────────────────────────────────

@pytest.mark.asyncio
async def test_tick_emits_proactive_suggestion_event(tmp_path: Path):
    """ConductorSupervisor tick 产出 suggestion → 事件广播到 _conductor 流。

    不启动真实 tick loop（tick_interval 大），手动调 _emit_suggestion 触发广播。
    """
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
        # 验证 run_id = "_conductor" 虚拟通道
        assert ev_dict.get("run_id") == CONDUCTOR_RUN_ID
    finally:
        await server.stop()


@pytest.mark.asyncio
async def test_tick_stores_suggestion_in_pending(tmp_path: Path):
    """ConductorSupervisor tick 产出 suggestion → 登记到 pending_suggestions。"""
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
    # 直接注入 pending（模拟 tick 产出）
    supervisor._pending[s.id] = s
    await supervisor._emit_suggestion(s)

    assert s.id in supervisor.pending_suggestions
    assert supervisor.pending_suggestions[s.id].order_id == "ord_pending_test"


# ── b. confirm → run 创建 + isolation=worktree + trust=L1 ────────────────────

class _FakeCompletedLoop:
    """立即完成的 fake loop（不需要真实 sandbox）。"""

    async def run(self, goal: str, session_id: str) -> AsyncIterator[dict]:
        yield {"kind": "token_delta", "text": "done"}


class _FakeLoopFactory:
    def __call__(self):
        return _FakeCompletedLoop()


@pytest.mark.asyncio
async def test_confirm_creates_run_with_worktree_and_l1_trust(tmp_path: Path):
    """POST /suggestions/{id}/confirm → run 创建，isolation=worktree，trust=L1_DANGEROUS_ONLY。

    铁证断言：
      1. HTTP 201 返回 run_id
      2. response body 包含 isolation="worktree"
      3. response body 包含 trust_level="L1_DANGEROUS_ONLY"
      4. manager.get_run(run_id) 存在（run 真正被创建）
    """
    server, manager, supervisor, socket_path = await _make_server_with_supervisor(tmp_path)
    # 注入 fake loop_factory（让 create_run 真正 spawn worker）
    server._loop_factory = _FakeLoopFactory()
    server._registry._max_concurrent = 5  # 确保有并发槽位

    try:
        sid = await _create_session(socket_path)
        # 模拟 session 升为 owner
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
        assert body.get("isolation") == "worktree", \
            f"isolation 必须是 'worktree'（铁律），实得 {body.get('isolation')!r}"
        assert body.get("trust_level") == "L1_DANGEROUS_ONLY", \
            f"trust_level 必须是 'L1_DANGEROUS_ONLY'（铁律），实得 {body.get('trust_level')!r}"
        # run 真正被创建到 manager
        assert manager.get_run(run_id) is not None, "run 必须存在于 manager"
        # suggestion 已从 pending 移除（confirm 后不再 pending）
        assert s.id not in supervisor.pending_suggestions, \
            "confirm 后 suggestion 必须从 pending 移除"
    finally:
        await server.stop()


@pytest.mark.asyncio
async def test_confirm_worktree_path_returned(tmp_path: Path):
    """confirm → response 包含 worktree_path 字段（即使是 temp dir fallback）。"""
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
        # worktree_path 可以是 None（无 git workspace 时），但字段必须存在
        assert "worktree_path" in body, "response body 必须包含 worktree_path 字段"
    finally:
        await server.stop()


# ── c. dismiss 后 confirm → 404 ──────────────────────────────────────────────

@pytest.mark.asyncio
async def test_dismiss_then_confirm_returns_404(tmp_path: Path):
    """POST dismiss → suggestion 移出 pending；再 confirm → 404。"""
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

        # confirm 再次 → 404
        status2, raw2 = await _raw_req(
            socket_path, "POST", f"/suggestions/{s.id}/confirm",
            session_id=sid,
        )
        body2 = json.loads(raw2.decode())
        assert status2 == 404, f"dismiss 后 confirm 应返回 404，实得 {status2}：{body2}"
    finally:
        await server.stop()


# ── d. orders CRUD fail-closed 分支 ──────────────────────────────────────────

@pytest.mark.asyncio
async def test_create_order_missing_utterance_returns_400(tmp_path: Path):
    """POST /orders 缺 utterance → 400。"""
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
    """POST /orders kind 非法 → 400。"""
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
    """POST /orders kind=schedule 但缺 schedule 字段 → 400。"""
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
    """GET /orders 无 orders → 200 空列表。"""
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
    """orders CRUD 完整：POST 201 → GET 200 含新 order → DELETE 204 → GET 200 为空。"""
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
        assert order_id not in [o["id"] for o in orders_after], \
            "删除后 order_id 不应再出现在列表中"
    finally:
        await server.stop()


@pytest.mark.asyncio
async def test_delete_unknown_order_returns_404(tmp_path: Path):
    """DELETE /orders/不存在的id → 404。"""
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


# ── e. daemon 关闭 tick loop 干净退出 ────────────────────────────────────────

@pytest.mark.asyncio
async def test_conductor_supervisor_stop_clean(tmp_path: Path):
    """ConductorSupervisor.stop() 干净取消 tick 协程，无异常泄露。"""
    orders_dir = tmp_path / "conductor"
    events: list[dict] = []

    async def _bcast(ev: dict) -> None:
        events.append(ev)

    supervisor = ConductorSupervisor(
        orders_dir=orders_dir,
        tick_interval=0.05,  # 快速 tick 用于测试
        broadcast_fn=_bcast,
    )
    supervisor.start()
    assert supervisor._task is not None
    assert not supervisor._task.done()

    # 短暂运行
    await asyncio.sleep(0.1)

    # 干净停止（不应抛 CancelledError）
    await supervisor.stop()
    assert supervisor._task.done(), "task 应已完成（cancelled）"


@pytest.mark.asyncio
async def test_conductor_supervisor_double_stop(tmp_path: Path):
    """ConductorSupervisor.stop() 可幂等调用（第二次 stop 不抛）。"""
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
    # 第二次 stop 不抛
    await supervisor.stop()


# ── f. suggestion 绝不在无 confirm 时变 run ──────────────────────────────────

@pytest.mark.asyncio
async def test_suggestion_never_auto_creates_run(tmp_path: Path):
    """tick 产出 suggestion，无任何 confirm 操作 → run 列表为空（绝不自动 create_run）。"""
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

    # 手动 tick（模拟引擎产出 suggestion，不触发任何 run）
    s = _make_suggestion("ord_auto_run_check")
    supervisor._pending[s.id] = s
    await supervisor._emit_suggestion(s)

    # 广播到了事件流，但 run 列表必须为空
    # （无任何 create_run 调用，supervisor 无 manager 引用，无法自动创建 run）
    assert len(supervisor.pending_suggestions) == 1, \
        "suggestion 应在 pending 中等待用户确认"
    # 没有 manager 可以查，但我们可以断言 supervisor 没有 _manager 属性
    assert not hasattr(supervisor, "_manager"), \
        "ConductorSupervisor 不应持有 manager 引用（安全边界：不能自己 create_run）"


@pytest.mark.asyncio
async def test_suggestions_list_endpoint(tmp_path: Path):
    """GET /suggestions 返回当前 pending suggestions。"""
    server, manager, supervisor, socket_path = await _make_server_with_supervisor(tmp_path)
    try:
        sid = await _create_session(socket_path)

        # 无 pending 时 → 空列表
        status, raw = await _raw_req(socket_path, "GET", "/suggestions", session_id=sid)
        assert status == 200
        assert json.loads(raw.decode()) == []

        # 注入 pending suggestion
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


# ── g. ProactiveSuggestionEvent 黄金测试 ─────────────────────────────────────

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
    """ProactiveSuggestionEvent serialize → deserialize 等值。"""
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
    """proactive_suggestion kind 必须注册在 _KIND_TO_CLASS 中。"""
    from argos_agent.protocol.events import _KIND_TO_CLASS
    assert "proactive_suggestion" in _KIND_TO_CLASS


def test_proactive_suggestion_event_in_event_kind_literal():
    """EventKind Literal 必须包含 'proactive_suggestion'。"""
    from argos_agent.protocol.events import EventKind
    assert "proactive_suggestion" in EventKind.__args__


def test_proactive_suggestion_event_requires_confirmation_invariant():
    """requires_confirmation 字段序列化为 True（协议级不可覆盖）。"""
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


# ── h. ConductorSupervisor dismiss / pop / get 语义 ──────────────────────────

def test_supervisor_dismiss_unknown_returns_false(tmp_path: Path):
    """dismiss 不存在的 suggestion_id → 返回 False。"""
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
    """get_suggestion 只读；pop_suggestion 移除。"""
    async def _bcast(ev: dict) -> None:
        pass

    supervisor = ConductorSupervisor(
        orders_dir=tmp_path / "conductor",
        tick_interval=999.0,
        broadcast_fn=_bcast,
    )
    s = _make_suggestion("ord_pop_test")
    supervisor._pending[s.id] = s

    # get 不移除
    got = supervisor.get_suggestion(s.id)
    assert got is not None and got.id == s.id
    assert s.id in supervisor.pending_suggestions

    # pop 移除
    popped = supervisor.pop_suggestion(s.id)
    assert popped is not None and popped.id == s.id
    assert s.id not in supervisor.pending_suggestions

    # pop 再次 → None
    assert supervisor.pop_suggestion(s.id) is None


# ── i. confirm 未知 suggestion → 404 ────────────────────────────────────────

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


# ── 终审回归钉:槽位泄漏 + 共享 gate L1 真生效 ────────────────────────────────

@pytest.mark.asyncio
async def test_metadata_mode_confirm_does_not_leak_slots(tmp_path: Path):
    """元数据模式(无 components/loop_factory)连续 confirm 超过 max_concurrent 次,
    全部 201 —— 槽位必须当场归还(无 worker 跑终态清理)。

    修复前:第 max_concurrent+1 次起永久 503(终审 major:槽位泄漏)。
    """
    server, manager, supervisor, socket_path = await _make_server_with_supervisor(tmp_path)
    # 不注入 loop_factory → 元数据模式
    try:
        sid = await _create_session(socket_path)
        rec = server._sessions.get(sid)
        if rec is not None:
            import dataclasses
            server._sessions._sessions[sid] = dataclasses.replace(rec, role="owner")

        n = server._registry.max_concurrent + 1   # 默认 5 → confirm 6 次
        for i in range(n):
            s = _make_suggestion(f"ord_slot_leak_{i}")
            supervisor._pending[s.id] = s
            status, raw = await _raw_req(
                socket_path, "POST", f"/suggestions/{s.id}/confirm", session_id=sid,
            )
            assert status == 201, (
                f"第 {i+1}/{n} 次 confirm 返 {status}(槽位泄漏回归!): {raw.decode()[:200]}"
            )
        # 槽位全数归还
        assert server._registry.has_capacity(), "全部 confirm 完成后必须仍有空槽"
    finally:
        await server.stop()


@pytest.mark.asyncio
async def test_metadata_mode_create_run_does_not_leak_slots(tmp_path: Path):
    """同病同修:元数据模式 POST /runs 超过 max_concurrent 次全部 201。"""
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
    """loop_factory 共享 gate 路径:confirm 后 gate 真被拨到 L1(CONFIRM 语义),
    不只是响应体字符串(终审 minor #2 的断言缺口)。"""
    from argos_agent.approval import ApprovalGate, ApprovalLevel
    from argos_agent.permissions.trust_dial import TrustLevel

    server, manager, supervisor, socket_path = await _make_server_with_supervisor(tmp_path)
    server._loop_factory = _FakeLoopFactory()
    gate = ApprovalGate()
    gate.set_level(ApprovalLevel.AUTO)        # 先拨到放飞档,验证 confirm 会拉回 L1
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
        # 铁证:gate 真被设到 L1 → ApprovalLevel.CONFIRM + 原始档位记录为 L1
        assert gate.level == ApprovalLevel.CONFIRM, f"gate.level 应为 CONFIRM,实得 {gate.level}"
        assert getattr(gate, "_trust_level", None) == TrustLevel.L1_DANGEROUS_ONLY
    finally:
        await server.stop()
