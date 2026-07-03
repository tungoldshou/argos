from __future__ import annotations

import asyncio
import json
import time
import uuid
from pathlib import Path
from typing import Any, AsyncIterator

import pytest

from argos.approval import ApprovalGate, ApprovalLevel, Decision
from argos.daemon.manager import RunManager
from argos.daemon.server import DaemonHTTPServer
from argos.daemon.worker import DaemonApprovalGate, RunWorker



class GateHolder:
    def __init__(self) -> None:
        self.gate: Any = None


class FakeApprovalLoop:

    def __init__(self, *, gate_holder: GateHolder, action: str = "write_file",
                 call_id: str | None = None):
        self._holder = gate_holder
        self._action = action
        self._call_id = call_id or uuid.uuid4().hex[:12]
        self.decision_received: Decision | None = None
        self.call_id = self._call_id

    async def run(self, goal: str, session_id: str) -> AsyncIterator[dict]:
        yield {"kind": "token_delta", "text": "preparing approval request"}
        await asyncio.sleep(0.05)

        gate = self._holder.gate
        assert gate is not None, "GateHolder.gate 未被设置"

        decision = await gate.request(
            self._action,
            {"path": "/tmp/test.txt", "content": "hello"},
            description=f"将写入 /tmp/test.txt (action={self._action})",
            risk="medium",
            call_id=self._call_id,
        )
        self.decision_received = decision

        yield {
            "kind": "approval_done",
            "call_id": self._call_id,
            "approved": decision.approved,
            "decision_kind": decision.kind,
        }

        yield {"kind": "verify_verdict",
               "verdict": {"status": "passed", "reason": "fake done"}}


class FakeApprovalLoopFactory:

    def __init__(self, loop: FakeApprovalLoop):
        self._loop = loop

    def __call__(self) -> FakeApprovalLoop:
        return self._loop


class GateSetterWorker(RunWorker):

    def __init__(self, *args, gate_holder: GateHolder, **kwargs):
        super().__init__(*args, **kwargs)
        self._gate_holder = gate_holder
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



@pytest.mark.asyncio
async def test_approval_circuit_full(tmp_path: Path):
    socket_path = tmp_path / "s.sock"
    manager = RunManager(
        runs_dir=tmp_path / "runs",
        index_path=tmp_path / "index.json",
    )

    real_gate = ApprovalGate(level=ApprovalLevel.CONFIRM)
    holder = GateHolder()
    fake_loop = FakeApprovalLoop(gate_holder=holder, action="write_file")

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

        await _wait_run_state(manager, run_id, "running", timeout=3.0)

        from argos.daemon.client import DaemonClient
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

        await _wait_run_state(manager, run_id, "completed", timeout=5.0)

        assert fake_loop.decision_received is not None
        assert fake_loop.decision_received.kind == "once"
        assert fake_loop.decision_received.approved is True

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



@pytest.mark.slow
@pytest.mark.asyncio
async def test_approval_wrong_call_id_returns_409(tmp_path: Path):
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

        await _wait_run_state(manager, run_id, "running", timeout=3.0)
        await asyncio.sleep(0.3)

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



@pytest.mark.asyncio
async def test_approval_timeout_deny(tmp_path: Path):
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
        approval_timeout_s=1.0,
        gate_holder=holder,
    )
    srv = DaemonHTTPServer(manager=manager, socket_path=socket_path)
    srv._workers[run_id] = worker
    await srv.start()

    task = asyncio.create_task(worker.run(), name=f"run-{run_id}")
    try:
        await _wait_run_state(manager, run_id, "completed", timeout=10.0)

        assert fake_loop.decision_received is not None
        assert fake_loop.decision_received.approved is False
        assert fake_loop.decision_received.kind == "deny"

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



@pytest.mark.asyncio
async def test_concurrent_runs_approval_isolation(tmp_path: Path):
    socket_path = tmp_path / "s.sock"
    manager = RunManager(
        runs_dir=tmp_path / "runs",
        index_path=tmp_path / "index.json",
    )

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

        await _wait_run_state(manager, run_id_a, "running", timeout=3.0)
        await _wait_run_state(manager, run_id_b, "running", timeout=3.0)
        await asyncio.sleep(0.3)

        status, raw = await _raw_req(
            socket_path,
            "POST", f"/runs/{run_id_b}/approval/{call_id_a}",
            session_id=sid,
            body={"decision": "once"},
        )
        assert status in (404, 409), (
            f"run B 不应接受 run A 的 call_id,但返回 {status}: {raw.decode()}"
        )

        status, raw = await _raw_req(
            socket_path,
            "POST", f"/runs/{run_id_a}/approval/{call_id_a}",
            session_id=sid,
            body={"decision": "once"},
        )
        assert status == 200, f"run A 审批应成功: {status}: {raw.decode()}"

        status, raw = await _raw_req(
            socket_path,
            "POST", f"/runs/{run_id_b}/approval/{call_id_b}",
            session_id=sid,
            body={"decision": "always"},
        )
        assert status == 200, f"run B 审批应成功: {status}: {raw.decode()}"

        await _wait_run_state(manager, run_id_a, "completed", timeout=5.0)
        await _wait_run_state(manager, run_id_b, "completed", timeout=5.0)

        assert loop_a.decision_received is not None
        assert loop_a.decision_received.kind == "once"
        assert loop_b.decision_received is not None
        assert loop_b.decision_received.kind == "always"

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


# ══════════════════════════════════════════════════════════════════════════
#
# ══════════════════════════════════════════════════════════════════════════

class FakePlanLoop:

    def __init__(self, *, call_id: str | None = None, decision_timeout_s: float = 30.0):
        _call_id = call_id or uuid.uuid4().hex[:12]
        self._plan_decision_event: asyncio.Event = asyncio.Event()
        self._plan_decision: Any = None
        self._plan_call_registry: dict[str, asyncio.Event] = {}
        self.mode: str = "plan"
        self.call_id = _call_id
        self._decision_timeout_s = decision_timeout_s
        self.decision_received: Any = None

    def respond_plan_decision(self, call_id: str, action: str,
                              feedback: str | None = None) -> bool:
        if call_id not in self._plan_call_registry:
            return False
        from argos.core.plan_mode import ExitPlanMode
        result = ExitPlanMode(self, action, feedback)
        if result.startswith("错误:"):
            return False
        self._plan_call_registry.pop(call_id, None)
        return True

    async def run(self, goal: str, session_id: str) -> AsyncIterator[dict]:
        yield {"kind": "token_delta", "text": "generating plan..."}

        self._plan_call_registry[self.call_id] = self._plan_decision_event

        try:
            await asyncio.wait_for(
                self._plan_decision_event.wait(),
                timeout=self._decision_timeout_s,
            )
        except asyncio.TimeoutError:
            yield {"kind": "error", "message": "plan_decision 超时", "chain": []}
            return

        self.decision_received = self._plan_decision

        yield {
            "kind": "plan_decision_applied",
            "action": self._plan_decision.action if self._plan_decision else "unknown",
        }
        yield {"kind": "verify_verdict",
               "verdict": {"status": "passed", "reason": "plan fake done"}}


class FakePlanLoopFactory:
    def __init__(self, loop: FakePlanLoop):
        self._loop = loop

    def __call__(self) -> FakePlanLoop:
        return self._loop



@pytest.mark.asyncio
async def test_plan_decision_full_circuit(tmp_path: Path):
    socket_path = tmp_path / "s.sock"
    manager = RunManager(
        runs_dir=tmp_path / "runs",
        index_path=tmp_path / "index.json",
    )
    fake_loop = FakePlanLoop()
    run_id = await manager.create_run(goal="test plan decision", workspace=str(tmp_path))
    worker = RunWorker(
        run_id=run_id, manager=manager,
        loop_factory=FakePlanLoopFactory(fake_loop),
        gate=None,
    )
    worker._loop = fake_loop

    srv = DaemonHTTPServer(manager=manager, socket_path=socket_path)
    srv._workers[run_id] = worker
    await srv.start()

    task = asyncio.create_task(worker.run(), name=f"run-{run_id}")
    try:
        sid = await _create_session(socket_path)
        await _wait_run_state(manager, run_id, "running", timeout=3.0)
        deadline = time.monotonic() + 3.0
        while time.monotonic() < deadline:
            if fake_loop.call_id in fake_loop._plan_call_registry:
                break
            await asyncio.sleep(0.02)
        assert fake_loop.call_id in fake_loop._plan_call_registry, (
            "FakePlanLoop 未注册 call_id"
        )

        # POST plan_decision(approve_start)
        status, raw = await _raw_req(
            socket_path,
            "POST", f"/runs/{run_id}/plan_decision",
            session_id=sid,
            body={"call_id": fake_loop.call_id, "action": "approve_start"},
        )
        assert status == 200, f"预期 200,实际 {status}: {raw.decode()}"
        resp = json.loads(raw.decode())
        assert resp["action"] == "approve_start"
        assert resp["state"] == "applied"

        await _wait_run_state(manager, run_id, "completed", timeout=5.0)

        assert fake_loop.decision_received is not None
        assert fake_loop.decision_received.action == "approve_start"

    finally:
        task.cancel()
        try:
            await task
        except (asyncio.CancelledError, Exception):
            pass
        await srv.stop()
        manager.close()



@pytest.mark.asyncio
async def test_plan_decision_unknown_run_404(tmp_path: Path):
    """POST /runs/nonexistent/plan_decision → 404。"""
    socket_path = tmp_path / "s.sock"
    manager = RunManager(
        runs_dir=tmp_path / "runs",
        index_path=tmp_path / "index.json",
    )
    srv = DaemonHTTPServer(manager=manager, socket_path=socket_path)
    await srv.start()
    try:
        sid = await _create_session(socket_path)
        status, raw = await _raw_req(
            socket_path,
            "POST", "/runs/nonexistent_run/plan_decision",
            session_id=sid,
            body={"call_id": "abc123", "action": "approve_start"},
        )
        assert status == 404, f"预期 404,实际 {status}: {raw.decode()}"
    finally:
        await srv.stop()
        manager.close()



@pytest.mark.asyncio
async def test_plan_decision_no_loop_409(tmp_path: Path):
    socket_path = tmp_path / "s.sock"
    manager = RunManager(
        runs_dir=tmp_path / "runs",
        index_path=tmp_path / "index.json",
    )
    run_id = await manager.create_run(goal="no loop run", workspace=str(tmp_path))

    class NoLoopWorker:
        state = "running"
        _loop = None

    srv = DaemonHTTPServer(manager=manager, socket_path=socket_path)
    srv._workers[run_id] = NoLoopWorker()  # type: ignore[assignment]
    await srv.start()
    try:
        sid = await _create_session(socket_path)
        status, raw = await _raw_req(
            socket_path,
            "POST", f"/runs/{run_id}/plan_decision",
            session_id=sid,
            body={"call_id": "abc123", "action": "approve_start"},
        )
        assert status == 409, f"预期 409,实际 {status}: {raw.decode()}"
    finally:
        await srv.stop()
        manager.close()



@pytest.mark.asyncio
async def test_plan_decision_unknown_call_id_409(tmp_path: Path):
    socket_path = tmp_path / "s.sock"
    manager = RunManager(
        runs_dir=tmp_path / "runs",
        index_path=tmp_path / "index.json",
    )
    fake_loop = FakePlanLoop()
    run_id = await manager.create_run(goal="unknown call_id", workspace=str(tmp_path))
    worker = RunWorker(
        run_id=run_id, manager=manager,
        loop_factory=FakePlanLoopFactory(fake_loop),
        gate=None,
    )
    worker._loop = fake_loop

    srv = DaemonHTTPServer(manager=manager, socket_path=socket_path)
    srv._workers[run_id] = worker
    await srv.start()
    try:
        sid = await _create_session(socket_path)
        status, raw = await _raw_req(
            socket_path,
            "POST", f"/runs/{run_id}/plan_decision",
            session_id=sid,
            body={"call_id": "deadbeef1234", "action": "approve_start"},
        )
        assert status == 409, f"预期 409,实际 {status}: {raw.decode()}"
    finally:
        await srv.stop()
        manager.close()



@pytest.mark.asyncio
async def test_plan_decision_invalid_action_400(tmp_path: Path):
    socket_path = tmp_path / "s.sock"
    manager = RunManager(
        runs_dir=tmp_path / "runs",
        index_path=tmp_path / "index.json",
    )
    fake_loop = FakePlanLoop()
    fake_loop._plan_call_registry[fake_loop.call_id] = fake_loop._plan_decision_event

    run_id = await manager.create_run(goal="invalid action", workspace=str(tmp_path))
    worker = RunWorker(
        run_id=run_id, manager=manager,
        loop_factory=FakePlanLoopFactory(fake_loop),
        gate=None,
    )
    worker._loop = fake_loop

    srv = DaemonHTTPServer(manager=manager, socket_path=socket_path)
    srv._workers[run_id] = worker
    await srv.start()
    try:
        sid = await _create_session(socket_path)
        status, raw = await _raw_req(
            socket_path,
            "POST", f"/runs/{run_id}/plan_decision",
            session_id=sid,
            body={"call_id": fake_loop.call_id, "action": "invalid_action_xyz"},
        )
        assert status == 400, f"预期 400,实际 {status}: {raw.decode()}"
    finally:
        await srv.stop()
        manager.close()



@pytest.mark.asyncio
async def test_plan_decision_refine_missing_feedback_400(tmp_path: Path):
    socket_path = tmp_path / "s.sock"
    manager = RunManager(
        runs_dir=tmp_path / "runs",
        index_path=tmp_path / "index.json",
    )
    fake_loop = FakePlanLoop()
    fake_loop._plan_call_registry[fake_loop.call_id] = fake_loop._plan_decision_event

    run_id = await manager.create_run(goal="refine missing feedback", workspace=str(tmp_path))
    worker = RunWorker(
        run_id=run_id, manager=manager,
        loop_factory=FakePlanLoopFactory(fake_loop),
        gate=None,
    )
    worker._loop = fake_loop

    srv = DaemonHTTPServer(manager=manager, socket_path=socket_path)
    srv._workers[run_id] = worker
    await srv.start()
    try:
        sid = await _create_session(socket_path)
        status, raw = await _raw_req(
            socket_path,
            "POST", f"/runs/{run_id}/plan_decision",
            session_id=sid,
            body={"call_id": fake_loop.call_id, "action": "refine"},
        )
        assert status == 400, f"预期 400,实际 {status}: {raw.decode()}"
    finally:
        await srv.stop()
        manager.close()



@pytest.mark.asyncio
async def test_plan_decision_cross_run_isolation(tmp_path: Path):
    socket_path = tmp_path / "s.sock"
    manager = RunManager(
        runs_dir=tmp_path / "runs",
        index_path=tmp_path / "index.json",
    )
    loop_a = FakePlanLoop(call_id="call_aaaaaa")
    loop_b = FakePlanLoop(call_id="call_bbbbbb")
    loop_a._plan_call_registry[loop_a.call_id] = loop_a._plan_decision_event
    loop_b._plan_call_registry[loop_b.call_id] = loop_b._plan_decision_event

    run_id_a = await manager.create_run(goal="plan run A", workspace=str(tmp_path))
    run_id_b = await manager.create_run(goal="plan run B", workspace=str(tmp_path))

    worker_a = RunWorker(
        run_id=run_id_a, manager=manager,
        loop_factory=FakePlanLoopFactory(loop_a), gate=None,
    )
    worker_b = RunWorker(
        run_id=run_id_b, manager=manager,
        loop_factory=FakePlanLoopFactory(loop_b), gate=None,
    )
    worker_a._loop = loop_a
    worker_b._loop = loop_b

    srv = DaemonHTTPServer(manager=manager, socket_path=socket_path)
    srv._workers[run_id_a] = worker_a
    srv._workers[run_id_b] = worker_b
    await srv.start()

    task_a = asyncio.create_task(worker_a.run(), name=f"run-{run_id_a}")
    task_b = asyncio.create_task(worker_b.run(), name=f"run-{run_id_b}")
    try:
        sid = await _create_session(socket_path)

        status, raw = await _raw_req(
            socket_path,
            "POST", f"/runs/{run_id_b}/plan_decision",
            session_id=sid,
            body={"call_id": loop_a.call_id, "action": "approve_start"},
        )
        assert status == 409, (
            f"run B 不应接受 run A 的 call_id,但返回 {status}: {raw.decode()}"
        )

        status, raw = await _raw_req(
            socket_path,
            "POST", f"/runs/{run_id_a}/plan_decision",
            session_id=sid,
            body={"call_id": loop_a.call_id, "action": "approve_start"},
        )
        assert status == 200, f"run A plan_decision 应成功: {status}: {raw.decode()}"

        status, raw = await _raw_req(
            socket_path,
            "POST", f"/runs/{run_id_b}/plan_decision",
            session_id=sid,
            body={"call_id": loop_b.call_id, "action": "keep_planning"},
        )
        assert status == 200, f"run B plan_decision 应成功: {status}: {raw.decode()}"

        # run A: approve_start
        deadline = time.monotonic() + 2.0
        while time.monotonic() < deadline and loop_a.decision_received is None:
            await asyncio.sleep(0.02)
        assert loop_a.decision_received is not None
        assert loop_a.decision_received.action == "approve_start", (
            f"run A 应收到 approve_start,实际 {loop_a.decision_received}"
        )

        deadline = time.monotonic() + 2.0
        while time.monotonic() < deadline and loop_b.decision_received is None:
            await asyncio.sleep(0.02)
        assert loop_b.decision_received is not None
        assert loop_b.decision_received.action == "keep_planning", (
            f"run B 应收到 keep_planning,实际 {loop_b.decision_received}"
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



@pytest.mark.asyncio
async def test_plan_decision_observer_session_rejected(tmp_path: Path):
    socket_path = tmp_path / "s.sock"
    manager = RunManager(
        runs_dir=tmp_path / "runs",
        index_path=tmp_path / "index.json",
    )
    fake_loop = FakePlanLoop()
    fake_loop._plan_call_registry[fake_loop.call_id] = fake_loop._plan_decision_event

    run_id = await manager.create_run(goal="observer rejected", workspace=str(tmp_path))
    worker = RunWorker(
        run_id=run_id, manager=manager,
        loop_factory=FakePlanLoopFactory(fake_loop), gate=None,
    )
    worker._loop = fake_loop

    srv = DaemonHTTPServer(manager=manager, socket_path=socket_path)
    srv._workers[run_id] = worker
    await srv.start()
    try:
        _owner_sid = await _create_session(socket_path)  # noqa: F841
        obs_sid = await _create_session(socket_path)

        status, raw = await _raw_req(
            socket_path,
            "POST", f"/runs/{run_id}/plan_decision",
            session_id=obs_sid,
            body={"call_id": fake_loop.call_id, "action": "approve_start"},
        )
        assert status == 403, (
            f"observer 会话应被拒(403),实际 {status}: {raw.decode()}"
        )
    finally:
        await srv.stop()
        manager.close()
