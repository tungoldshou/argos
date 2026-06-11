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


# ══════════════════════════════════════════════════════════════════════════
# P3 plan_decision 路径测试
#
# FakePlanLoop 直接管理 _plan_call_registry + _plan_decision_event,
# 模拟 AgentLoop._plan_phase_round 的 call_id 注册行为,供 respond_plan_decision 使用。
# RunWorker 的 loop_factory 返回此实例;server 通过 worker._loop 找到它。
# ══════════════════════════════════════════════════════════════════════════

class FakePlanLoop:
    """模拟 AgentLoop plan 决策挂起路径的 fake loop。

    · run() 流式产出一个 token_delta + 注册一个 call_id 到 _plan_call_registry
    · 然后挂起等待 respond_plan_decision(call_id, action) 被调用
    · 收到后产出结果事件并完成
    """

    def __init__(self, *, call_id: str | None = None, decision_timeout_s: float = 30.0):
        _call_id = call_id or uuid.uuid4().hex[:12]
        # 模拟 AgentLoop 中的字段(respond_plan_decision + server 直接访问这些属性)
        self._plan_decision_event: asyncio.Event = asyncio.Event()
        self._plan_decision: Any = None
        self._plan_call_registry: dict[str, asyncio.Event] = {}
        self.mode: str = "plan"  # 在 plan 阶段挂起时处于 plan mode
        self.call_id = _call_id
        self._decision_timeout_s = decision_timeout_s
        self.decision_received: Any = None  # 供测试读取

    def respond_plan_decision(self, call_id: str, action: str,
                              feedback: str | None = None) -> bool:
        """与 AgentLoop.respond_plan_decision 同签名。"""
        if call_id not in self._plan_call_registry:
            return False
        from argos_agent.core.plan_mode import ExitPlanMode
        result = ExitPlanMode(self, action, feedback)
        if result.startswith("错误:"):
            return False
        self._plan_call_registry.pop(call_id, None)
        return True

    async def run(self, goal: str, session_id: str) -> AsyncIterator[dict]:
        """模拟 run 阶段:注册 call_id → 挂起等决策 → 产出结果。"""
        yield {"kind": "token_delta", "text": "generating plan..."}

        # 注册 call_id(模拟 _plan_phase_round 的行为)
        self._plan_call_registry[self.call_id] = self._plan_decision_event

        # 挂起等待决策
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


# ── plan_decision: 完整正常路径 ────────────────────────────────────────

@pytest.mark.asyncio
async def test_plan_decision_full_circuit(tmp_path: Path):
    """POST /runs/{id}/plan_decision(approve_start) → loop 唤醒 → run 完成。"""
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
    # 手工将 loop 实例挂上 worker(server 通过 worker._loop 访问)
    worker._loop = fake_loop

    srv = DaemonHTTPServer(manager=manager, socket_path=socket_path)
    srv._workers[run_id] = worker
    await srv.start()

    task = asyncio.create_task(worker.run(), name=f"run-{run_id}")
    try:
        sid = await _create_session(socket_path)
        await _wait_run_state(manager, run_id, "running", timeout=3.0)
        # 等 loop 注册 call_id
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

        # run 应完成
        await _wait_run_state(manager, run_id, "completed", timeout=5.0)

        # decision 正确传达
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


# ── plan_decision: 404 run 不存在 ─────────────────────────────────────

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


# ── plan_decision: 409 无 loop ────────────────────────────────────────

@pytest.mark.asyncio
async def test_plan_decision_no_loop_409(tmp_path: Path):
    """run 存在但 worker._loop 为 None → 409。"""
    socket_path = tmp_path / "s.sock"
    manager = RunManager(
        runs_dir=tmp_path / "runs",
        index_path=tmp_path / "index.json",
    )
    run_id = await manager.create_run(goal="no loop run", workspace=str(tmp_path))

    # 构造 worker 但不设 _loop
    class NoLoopWorker:
        """最小 worker 存根:无 _loop 属性。"""
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


# ── plan_decision: 409 call_id 不在注册表 ─────────────────────────────

@pytest.mark.asyncio
async def test_plan_decision_unknown_call_id_409(tmp_path: Path):
    """call_id 不在 _plan_call_registry → 409。"""
    socket_path = tmp_path / "s.sock"
    manager = RunManager(
        runs_dir=tmp_path / "runs",
        index_path=tmp_path / "index.json",
    )
    fake_loop = FakePlanLoop()
    # 不注册任何 call_id(registry 为空)
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


# ── plan_decision: 400 非法 action ────────────────────────────────────

@pytest.mark.asyncio
async def test_plan_decision_invalid_action_400(tmp_path: Path):
    """action 非法 → 400。"""
    socket_path = tmp_path / "s.sock"
    manager = RunManager(
        runs_dir=tmp_path / "runs",
        index_path=tmp_path / "index.json",
    )
    fake_loop = FakePlanLoop()
    # 手工注册 call_id,使其通过 call_id 检查
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


# ── plan_decision: 400 refine 无 feedback ─────────────────────────────

@pytest.mark.asyncio
async def test_plan_decision_refine_missing_feedback_400(tmp_path: Path):
    """action=refine 但 feedback 缺失 → 400。"""
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
        # refine 无 feedback 字段
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


# ── plan_decision: 跨 run 隔离 ────────────────────────────────────────

@pytest.mark.asyncio
async def test_plan_decision_cross_run_isolation(tmp_path: Path):
    """run A 的 call_id 发给 run B → 409;各自 call_id 正确路由。"""
    socket_path = tmp_path / "s.sock"
    manager = RunManager(
        runs_dir=tmp_path / "runs",
        index_path=tmp_path / "index.json",
    )
    loop_a = FakePlanLoop(call_id="call_aaaaaa")
    loop_b = FakePlanLoop(call_id="call_bbbbbb")
    # 预注册 call_id
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

        # run A 的 call_id 发给 run B → 409
        status, raw = await _raw_req(
            socket_path,
            "POST", f"/runs/{run_id_b}/plan_decision",
            session_id=sid,
            body={"call_id": loop_a.call_id, "action": "approve_start"},
        )
        assert status == 409, (
            f"run B 不应接受 run A 的 call_id,但返回 {status}: {raw.decode()}"
        )

        # run A 的 call_id 发给 run A → 200
        status, raw = await _raw_req(
            socket_path,
            "POST", f"/runs/{run_id_a}/plan_decision",
            session_id=sid,
            body={"call_id": loop_a.call_id, "action": "approve_start"},
        )
        assert status == 200, f"run A plan_decision 应成功: {status}: {raw.decode()}"

        # run B 的 call_id 发给 run B → 200
        status, raw = await _raw_req(
            socket_path,
            "POST", f"/runs/{run_id_b}/plan_decision",
            session_id=sid,
            body={"call_id": loop_b.call_id, "action": "keep_planning"},
        )
        assert status == 200, f"run B plan_decision 应成功: {status}: {raw.decode()}"

        # decision 正确且不串
        # run A: approve_start
        deadline = time.monotonic() + 2.0
        while time.monotonic() < deadline and loop_a.decision_received is None:
            await asyncio.sleep(0.02)
        assert loop_a.decision_received is not None
        assert loop_a.decision_received.action == "approve_start", (
            f"run A 应收到 approve_start,实际 {loop_a.decision_received}"
        )

        # run B: keep_planning(loop_b 的 decision)
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


# ── plan_decision: observer 会话被拒(owner-only) ─────────────────────

@pytest.mark.asyncio
async def test_plan_decision_observer_session_rejected(tmp_path: Path):
    """observer 只读会话尝试 plan_decision → 403(owner-only 校验)。"""
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
        # 第一个 session = owner,第二个 session = observer(sessions.py:role logic)
        _owner_sid = await _create_session(socket_path)  # noqa: F841 — 占 owner 槽
        obs_sid = await _create_session(socket_path)     # 第二个 → observer 角色

        # observer 会话发送 plan_decision → 预期 403
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
