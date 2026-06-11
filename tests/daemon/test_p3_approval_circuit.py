"""P3 跨进程审批回路验收测试(spec §13 P3 验收标准)。

验收条目:
  a. run 触发审批 → SSE 可见 approval_request → POST approval(once) → run 继续 → 完成。
  b. 错 call_id → 409,run 不受影响,最终超时 deny。
  c. 无人批 → 超时 deny + 诚实 error 事件落盘。
  d. 两个并发 run 各自审批互不串(call_id 路由正确性)。

设计原则:
  · 所有测试用 DaemonApprovalGate 直接包装真 ApprovalGate,不依赖真模型。
  · FakeApprovalLoop 通过 gate_holder 拿到 DaemonApprovalGate 包装后的实例,
    确保 approval_request 事件真正经过 DaemonApprovalGate 走 SSE 扇出路径。
  · RunWorker.run() 内部会把 self._gate 替换为 DaemonApprovalGate;
    我们通过 GateHolder 让 loop 在运行时读取最新的 gate 引用。
"""
from __future__ import annotations

import asyncio
import json
import time
import uuid
from pathlib import Path
from typing import Any, AsyncIterator

import pytest

from argos_agent.approval import ApprovalGate, ApprovalLevel, Decision
from argos_agent.daemon.manager import RunManager
from argos_agent.daemon.server import DaemonHTTPServer
from argos_agent.daemon.worker import DaemonApprovalGate, RunWorker


# ── 测试工具 ──────────────────────────────────────────────────────────────

class GateHolder:
    """可变 gate 引用持有者:worker.run() 替换 gate 后,loop 通过此 holder 拿到新引用。"""
    def __init__(self) -> None:
        self.gate: Any = None  # 运行时由 worker 设置


class FakeApprovalLoop:
    """可控 fake loop:经 DaemonApprovalGate 触发一次审批后继续完成。

    gate_holder.gate 在 worker.run() 把真 gate 包装为 DaemonApprovalGate 后才有值。
    loop 在第一个 yield 后 sleep 一小段等 holder 被设置,再调 gate.request()。
    """

    def __init__(self, *, gate_holder: GateHolder, action: str = "write_file",
                 call_id: str | None = None):
        self._holder = gate_holder
        self._action = action
        self._call_id = call_id or uuid.uuid4().hex[:12]
        self.decision_received: Decision | None = None
        self.call_id = self._call_id  # 供测试读取

    async def run(self, goal: str, session_id: str) -> AsyncIterator[dict]:
        # 步骤 1: 让 worker.run() 完成 DaemonApprovalGate 包装
        yield {"kind": "token_delta", "text": "preparing approval request"}
        await asyncio.sleep(0.05)  # 等 holder.gate 被 worker 设置

        gate = self._holder.gate
        assert gate is not None, "GateHolder.gate 未被设置"

        # 步骤 2: 挂起等审批(经 DaemonApprovalGate → SSE 扇出 + Future 挂起)
        decision = await gate.request(
            self._action,
            {"path": "/tmp/test.txt", "content": "hello"},
            description=f"将写入 /tmp/test.txt (action={self._action})",
            risk="medium",
            call_id=self._call_id,
        )
        self.decision_received = decision

        # 步骤 3: 投结果事件
        yield {
            "kind": "approval_done",
            "call_id": self._call_id,
            "approved": decision.approved,
            "decision_kind": decision.kind,
        }

        # 步骤 4: 完成
        yield {"kind": "verify_verdict",
               "verdict": {"status": "passed", "reason": "fake done"}}


class FakeApprovalLoopFactory:
    """返回可共享同一个 loop 实例的 factory。"""

    def __init__(self, loop: FakeApprovalLoop):
        self._loop = loop

    def __call__(self) -> FakeApprovalLoop:
        return self._loop


class GateSetterWorker(RunWorker):
    """RunWorker 子类:预包装 DaemonApprovalGate 并通知 GateHolder。

    父类 run() 会检查 self._gate 是否为 DaemonApprovalGate 实例并跳过重包装
    (我们在 __init__ 里提前替换 self._gate 为 DaemonApprovalGate)。
    这样 holder.gate 和 srv._workers[id].gate 都指向同一个 DaemonApprovalGate 实例。
    """

    def __init__(self, *args, gate_holder: GateHolder, **kwargs):
        super().__init__(*args, **kwargs)
        self._gate_holder = gate_holder
        # 提前包装:父类 run() 的 DaemonApprovalGate 包装逻辑检查 isinstance,
        # 已是 DaemonApprovalGate 则跳过(我们在父类 run() 前手工包装好)。
        if self._gate is not None and not isinstance(self._gate, DaemonApprovalGate):
            wrapped = DaemonApprovalGate(
                self._gate,
                timeout_s=self._approval_timeout_s,
                run_id=self.run_id,
                manager=self._manager,
            )
            self._gate = wrapped
        self._gate_holder.gate = self._gate


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


async def _wait_run_state(manager: RunManager, run_id: str, state: str,
                           timeout: float = 5.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        entry = manager.get_run(run_id)
        if entry is not None and entry.state == state:
            return
        await asyncio.sleep(0.02)
    entry = manager.get_run(run_id)
    actual = entry.state if entry else "None"
    raise AssertionError(f"run {run_id} expected state={state!r}, got {actual!r}")


# ── a. 完整审批回路 ───────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_approval_circuit_full(tmp_path: Path):
    """run 触发审批 → SSE 可见 approval_request → POST approval(once) → run 完成。"""
    socket_path = tmp_path / "s.sock"
    manager = RunManager(
        runs_dir=tmp_path / "runs",
        index_path=tmp_path / "index.json",
    )

    # 构造 per-run gate + 可控 loop
    real_gate = ApprovalGate(level=ApprovalLevel.CONFIRM)
    holder = GateHolder()
    fake_loop = FakeApprovalLoop(gate_holder=holder, action="write_file")

    # 创建 run + worker(手工路径,不经 server create_run)
    run_id = await manager.create_run(goal="test approval", workspace=str(tmp_path))
    worker = GateSetterWorker(
        run_id=run_id, manager=manager,
        loop_factory=FakeApprovalLoopFactory(fake_loop),
        gate=real_gate,
        approval_timeout_s=10.0,
        gate_holder=holder,
    )

    srv = DaemonHTTPServer(manager=manager, socket_path=socket_path)
    srv._workers[run_id] = worker
    await srv.start()

    task = asyncio.create_task(worker.run(), name=f"run-{run_id}")
    try:
        sid = await _create_session(socket_path)

        # 等 run 进 running
        await _wait_run_state(manager, run_id, "running", timeout=3.0)

        # 订阅 SSE,等待 approval_request 事件
        from argos_agent.daemon.client import DaemonClient
        cli = DaemonClient(socket_path, timeout=8.0)
        seen_approval_request = False
        call_id: str | None = None
        seen_events: list[dict] = []
        deadline = time.monotonic() + 5.0
        async for ev in cli.subscribe_events(run_id, sid):
            seen_events.append(ev)
            if ev.get("kind") == "approval_request":
                seen_approval_request = True
                call_id = ev.get("call_id")
                break
            if time.monotonic() > deadline:
                break

        assert seen_approval_request, (
            f"approval_request 事件未出现,已收到: "
            f"{[e.get('kind') for e in seen_events]}"
        )
        assert call_id is not None

        # POST approval(once)
        status, raw = await _raw_req(
            socket_path,
            "POST", f"/runs/{run_id}/approval/{call_id}",
            session_id=sid,
            body={"decision": "once"},
        )
        assert status == 200, raw.decode()
        resp = json.loads(raw.decode())
        assert resp["decision"] == "once"
        assert resp["state"] == "applied"

        # 等 run 完成
        await _wait_run_state(manager, run_id, "completed", timeout=5.0)

        # decision 正确
        assert fake_loop.decision_received is not None
        assert fake_loop.decision_received.kind == "once"
        assert fake_loop.decision_received.approved is True

        # approval_response 事件落盘(审计可见性)
        events = list(manager.store.replay(run_id))
        kinds = [e.get("kind") for e in events]
        assert "approval_response" in kinds, (
            f"approval_response 未落盘,kinds={kinds}"
        )
        ar = next(e for e in events if e.get("kind") == "approval_response")
        assert ar["call_id"] == call_id
        assert ar["decision"] == "once"

    finally:
        task.cancel()
        try:
            await task
        except (asyncio.CancelledError, Exception):
            pass
        await srv.stop()
        manager.close()


# ── b. 错 call_id → 409,run 不受影响 ────────────────────────────────────

@pytest.mark.asyncio
async def test_approval_wrong_call_id_returns_409(tmp_path: Path):
    """错 call_id → 409/404,run 不受影响,最终超时 deny。"""
    socket_path = tmp_path / "s.sock"
    manager = RunManager(
        runs_dir=tmp_path / "runs",
        index_path=tmp_path / "index.json",
    )
    real_gate = ApprovalGate(level=ApprovalLevel.CONFIRM)
    holder = GateHolder()
    fake_loop = FakeApprovalLoop(gate_holder=holder, action="shell_cmd")

    run_id = await manager.create_run(
        goal="test wrong call_id", workspace=str(tmp_path),
    )
    worker = GateSetterWorker(
        run_id=run_id, manager=manager,
        loop_factory=FakeApprovalLoopFactory(fake_loop),
        gate=real_gate,
        approval_timeout_s=3.0,
        gate_holder=holder,
    )
    srv = DaemonHTTPServer(manager=manager, socket_path=socket_path)
    srv._workers[run_id] = worker
    await srv.start()

    task = asyncio.create_task(worker.run(), name=f"run-{run_id}")
    try:
        sid = await _create_session(socket_path)

        # 等 running + 等 gate.request() 挂起
        await _wait_run_state(manager, run_id, "running", timeout=3.0)
        await asyncio.sleep(0.3)

        # POST 错误 call_id
        wrong_id = uuid.uuid4().hex[:12]
        status, raw = await _raw_req(
            socket_path,
            "POST", f"/runs/{run_id}/approval/{wrong_id}",
            session_id=sid,
            body={"decision": "once"},
        )
        assert status in (404, 409), (
            f"期望 404/409,实际 {status}: {raw.decode()}"
        )
        body_obj = json.loads(raw.decode())
        assert "call_id" in body_obj.get("error", "") or "call_id" in body_obj.get("code", ""), (
            f"错误消息应提及 call_id: {body_obj}"
        )

        # run 不受影响,超时 deny 后完成
        await _wait_run_state(manager, run_id, "completed", timeout=8.0)

        assert fake_loop.decision_received is not None
        assert fake_loop.decision_received.approved is False

    finally:
        task.cancel()
        try:
            await task
        except (asyncio.CancelledError, Exception):
            pass
        await srv.stop()
        manager.close()


# ── c. 无人批 → 超时 deny + 诚实 error 事件 ─────────────────────────────

@pytest.mark.asyncio
async def test_approval_timeout_deny(tmp_path: Path):
    """无人批 → 超时 deny + 诚实 error 事件落盘。"""
    socket_path = tmp_path / "s.sock"
    manager = RunManager(
        runs_dir=tmp_path / "runs",
        index_path=tmp_path / "index.json",
    )
    real_gate = ApprovalGate(level=ApprovalLevel.CONFIRM)
    holder = GateHolder()
    fake_loop = FakeApprovalLoop(gate_holder=holder, action="risky_op")

    run_id = await manager.create_run(
        goal="test timeout deny", workspace=str(tmp_path),
    )
    worker = GateSetterWorker(
        run_id=run_id, manager=manager,
        loop_factory=FakeApprovalLoopFactory(fake_loop),
        gate=real_gate,
        approval_timeout_s=1.0,  # 1s 极短超时
        gate_holder=holder,
    )
    srv = DaemonHTTPServer(manager=manager, socket_path=socket_path)
    srv._workers[run_id] = worker
    await srv.start()

    task = asyncio.create_task(worker.run(), name=f"run-{run_id}")
    try:
        # 等 run 完成(超时 deny 后 loop 继续 → completed)
        await _wait_run_state(manager, run_id, "completed", timeout=10.0)

        # decision 是 deny(fail-closed)
        assert fake_loop.decision_received is not None
        assert fake_loop.decision_received.approved is False
        assert fake_loop.decision_received.kind == "deny"

        # error 事件落盘
        events = list(manager.store.replay(run_id))
        error_events = [e for e in events if e.get("kind") == "error"]
        assert error_events, (
            f"error 事件未落盘,kinds={[e.get('kind') for e in events]}"
        )
        combined_msg = " ".join(
            e.get("message", "") + " ".join(e.get("chain", []))
            for e in error_events
        )
        assert "超时" in combined_msg or "timeout" in combined_msg.lower(), (
            f"error 事件应含超时字样: {combined_msg}"
        )

    finally:
        task.cancel()
        try:
            await task
        except (asyncio.CancelledError, Exception):
            pass
        await srv.stop()
        manager.close()


# ── d. 两个并发 run 审批互不串 ──────────────────────────────────────────

@pytest.mark.asyncio
async def test_concurrent_runs_approval_isolation(tmp_path: Path):
    """两个并发 run 各自审批互不串(call_id 路由正确性)。"""
    socket_path = tmp_path / "s.sock"
    manager = RunManager(
        runs_dir=tmp_path / "runs",
        index_path=tmp_path / "index.json",
    )

    # 两个独立的 gate + holder + loop
    gate_a = ApprovalGate(level=ApprovalLevel.CONFIRM)
    gate_b = ApprovalGate(level=ApprovalLevel.CONFIRM)
    holder_a = GateHolder()
    holder_b = GateHolder()
    call_id_a = uuid.uuid4().hex[:12]
    call_id_b = uuid.uuid4().hex[:12]
    loop_a = FakeApprovalLoop(gate_holder=holder_a, action="action_a", call_id=call_id_a)
    loop_b = FakeApprovalLoop(gate_holder=holder_b, action="action_b", call_id=call_id_b)

    run_id_a = await manager.create_run(goal="run A", workspace=str(tmp_path))
    run_id_b = await manager.create_run(goal="run B", workspace=str(tmp_path))

    worker_a = GateSetterWorker(
        run_id=run_id_a, manager=manager,
        loop_factory=FakeApprovalLoopFactory(loop_a),
        gate=gate_a, approval_timeout_s=10.0, gate_holder=holder_a,
    )
    worker_b = GateSetterWorker(
        run_id=run_id_b, manager=manager,
        loop_factory=FakeApprovalLoopFactory(loop_b),
        gate=gate_b, approval_timeout_s=10.0, gate_holder=holder_b,
    )

    srv = DaemonHTTPServer(manager=manager, socket_path=socket_path)
    srv._workers[run_id_a] = worker_a
    srv._workers[run_id_b] = worker_b
    await srv.start()

    task_a = asyncio.create_task(worker_a.run(), name=f"run-{run_id_a}")
    task_b = asyncio.create_task(worker_b.run(), name=f"run-{run_id_b}")

    try:
        sid = await _create_session(socket_path)

        # 等两个 run 都进入 running + 挂起
        await _wait_run_state(manager, run_id_a, "running", timeout=3.0)
        await _wait_run_state(manager, run_id_b, "running", timeout=3.0)
        await asyncio.sleep(0.3)

        # run A 的 call_id 发到 run B → 409(call_id 不在 B 的 pending)
        status, raw = await _raw_req(
            socket_path,
            "POST", f"/runs/{run_id_b}/approval/{call_id_a}",
            session_id=sid,
            body={"decision": "once"},
        )
        assert status in (404, 409), (
            f"run B 不应接受 run A 的 call_id,但返回 {status}: {raw.decode()}"
        )

        # 正确路由:run A 的 call_id → run A
        status, raw = await _raw_req(
            socket_path,
            "POST", f"/runs/{run_id_a}/approval/{call_id_a}",
            session_id=sid,
            body={"decision": "once"},
        )
        assert status == 200, f"run A 审批应成功: {status}: {raw.decode()}"

        # 正确路由:run B 的 call_id → run B
        status, raw = await _raw_req(
            socket_path,
            "POST", f"/runs/{run_id_b}/approval/{call_id_b}",
            session_id=sid,
            body={"decision": "always"},
        )
        assert status == 200, f"run B 审批应成功: {status}: {raw.decode()}"

        # 等两个 run 都完成
        await _wait_run_state(manager, run_id_a, "completed", timeout=5.0)
        await _wait_run_state(manager, run_id_b, "completed", timeout=5.0)

        # 各自 decision 正确、不串
        assert loop_a.decision_received is not None
        assert loop_a.decision_received.kind == "once"
        assert loop_b.decision_received is not None
        assert loop_b.decision_received.kind == "always"

        # approval_response 事件落盘,call_id 字段正确
        events_a = list(manager.store.replay(run_id_a))
        events_b = list(manager.store.replay(run_id_b))
        ar_a = next((e for e in events_a if e.get("kind") == "approval_response"), None)
        ar_b = next((e for e in events_b if e.get("kind") == "approval_response"), None)
        assert ar_a is not None and ar_a["call_id"] == call_id_a, (
            f"run A approval_response 落盘错误: {ar_a}"
        )
        assert ar_b is not None and ar_b["call_id"] == call_id_b, (
            f"run B approval_response 落盘错误: {ar_b}"
        )

    finally:
        for t in (task_a, task_b):
            t.cancel()
            try:
                await t
            except (asyncio.CancelledError, Exception):
                pass
        await srv.stop()
        manager.close()
