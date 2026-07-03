from __future__ import annotations

import asyncio
import json
import time
import uuid
from pathlib import Path
from typing import AsyncIterator

import pytest
import pytest_asyncio

from argos.daemon.manager import RunManager
from argos.daemon.server import DaemonHTTPServer
from argos.daemon.worker import FakeLoop


# ── helpers ─────────────────────────────────────────────────────────────

async def _raw_req(socket_path: Path, method: str, path: str, *,
                   session_id: str | None = None,
                   body: dict | None = None,
                   timeout: float = 10.0):
    from argos.daemon.client import DaemonClient
    cli = DaemonClient(socket_path, timeout=timeout)
    status, _headers, raw = await cli._request(method, path,
                                                session_id=session_id,
                                                body=body)
    return status, raw


async def _create_session(socket_path: Path) -> str:
    status, raw = await _raw_req(socket_path, "POST", "/sessions")
    assert status == 201
    return json.loads(raw.decode())["session_id"]


async def _promote_to_owner(socket_path: Path, sid: str) -> None:
    pass


async def _create_run(socket_path: Path, sid: str, goal: str,
                      workspace: str = "") -> tuple[int, dict]:
    status, raw = await _raw_req(
        socket_path, "POST", "/runs",
        session_id=sid,
        body={"goal": goal, "workspace": workspace},
    )
    return status, json.loads(raw.decode())


async def _wait_run_state(socket_path: Path, sid: str, run_id: str,
                          target: str, timeout: float = 5.0) -> str:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        status, raw = await _raw_req(
            socket_path, "GET", f"/runs/{run_id}", session_id=sid
        )
        if status == 200:
            state = json.loads(raw.decode()).get("state", "")
            if state == target:
                return state
        await asyncio.sleep(0.05)
    raise TimeoutError(f"run {run_id} did not reach state={target!r} within {timeout}s")


async def _collect_sse_events(socket_path: Path, sid: str, run_id: str,
                               *, stop_state: str = "completed",
                               timeout: float = 8.0) -> list[dict]:
    events: list[dict] = []
    deadline = time.monotonic() + timeout

    from argos.daemon.client import DaemonClient
    cli = DaemonClient(socket_path, timeout=timeout)
    async for ev in cli.subscribe_events(run_id, sid):
        events.append(ev)
        kind = ev.get("kind", "")
        if kind == "state_change" and ev.get("to") in ("completed", "failed", "cancelled"):
            break
        if time.monotonic() > deadline:
            break
    return events


# ── fixtures ─────────────────────────────────────────────────────────────

def _make_fake_loop_factory(steps: int = 5, delay_s: float = 0.0):
    def factory():
        return FakeLoop(steps=steps, delay_s=delay_s)
    return factory


@pytest_asyncio.fixture
async def server_with_fake_loop(tmp_path: Path):
    runs_dir = tmp_path / "runs"
    index_path = tmp_path / "index.json"
    socket_path = tmp_path / "daemon.sock"
    manager = RunManager(runs_dir=runs_dir, index_path=index_path)
    loop_factory = _make_fake_loop_factory(steps=5, delay_s=0.0)
    srv = DaemonHTTPServer(
        manager=manager,
        socket_path=socket_path,
        loop_factory=loop_factory,
    )
    await srv.start()
    try:
        yield srv, manager, socket_path
    finally:
        await srv.stop()
        manager.close()


@pytest_asyncio.fixture
async def server_no_key(tmp_path: Path):
    from argos.daemon.server import _NO_KEY
    runs_dir = tmp_path / "runs"
    index_path = tmp_path / "index.json"
    socket_path = tmp_path / "daemon.sock"
    manager = RunManager(runs_dir=runs_dir, index_path=index_path)
    srv = DaemonHTTPServer(
        manager=manager,
        socket_path=socket_path,
        loop_factory=_NO_KEY,
    )
    await srv.start()
    try:
        yield srv, manager, socket_path
    finally:
        await srv.stop()
        manager.close()



@pytest.mark.asyncio
async def test_create_run_fires_worker_events_and_completes(
    server_with_fake_loop: tuple,
):
    srv, manager, socket_path = server_with_fake_loop

    sid = await _create_session(socket_path)

    status, body = await _create_run(socket_path, sid, goal="test goal")
    assert status == 201, f"create_run 应返回 201,实际 {status}: {body}"
    run_id = body["run_id"]

    final_state = await _wait_run_state(socket_path, sid, run_id, "completed", timeout=8.0)
    assert final_state == "completed"

    events = list(manager.store.replay(run_id))
    assert len(events) > 0, "JSONL 应有事件"
    kinds = {e.get("kind") for e in events}
    assert "token_delta" in kinds, f"应有 token_delta,实际 kinds={kinds}"
    assert "verify_verdict" in kinds, f"应有 verify_verdict,实际 kinds={kinds}"

    state_changes = [e for e in events if e.get("kind") == "state_change"]
    to_states = {e.get("to") for e in state_changes}
    assert "running" in to_states, f"应有 running state_change,实际={to_states}"
    assert "completed" in to_states, f"应有 completed state_change,实际={to_states}"

    seqs = [e["_seq"] for e in events if "_seq" in e]
    assert seqs == list(range(1, len(seqs) + 1)), f"_seq 应连续,实际={seqs[:10]}"


@pytest.mark.asyncio
async def test_sse_stream_receives_events(server_with_fake_loop: tuple):
    srv, manager, socket_path = server_with_fake_loop
    sid = await _create_session(socket_path)

    status, body = await _create_run(socket_path, sid, goal="sse test")
    assert status == 201
    run_id = body["run_id"]

    received = await _collect_sse_events(socket_path, sid, run_id, timeout=8.0)
    assert len(received) > 0, "SSE 应收到事件"
    kinds = {e.get("kind") for e in received}
    assert any(
        e.get("kind") == "state_change" and e.get("to") in ("completed",)
        for e in received
    ), f"应有 completed state_change,实际 kinds={kinds}"



class _WorkspaceCapturingFakeLoop:

    def __init__(self, *, steps: int = 5, delay_s: float = 0.0):
        self._steps = steps
        self._delay = delay_s
        self.captured_workspace: str | None = None

    async def run(self, goal: str, session_id: str):
        import argos.runtime as _runtime
        ctx = _runtime.current()
        self.captured_workspace = str(ctx.workspace)
        for i in range(self._steps):
            if self._delay:
                await asyncio.sleep(self._delay)
            yield {"kind": "token_delta", "text": f"step {i}", "step": i}
            yield {"kind": "code_action", "code": f"# step {i}", "step": i}
            yield {"kind": "code_result", "stdout": "", "value_repr": "", "exc": "", "ok": True, "step": i}
        yield {"kind": "verify_verdict", "verdict": {"status": "passed", "reason": "fake"}}


@pytest.mark.asyncio
async def test_two_concurrent_runs_do_not_cross_contaminate(tmp_path: Path):
    ws1 = tmp_path / "ws1"
    ws2 = tmp_path / "ws2"
    ws1.mkdir()
    ws2.mkdir()

    runs_dir = tmp_path / "runs"
    index_path = tmp_path / "index.json"
    socket_path = tmp_path / "daemon.sock"
    manager = RunManager(runs_dir=runs_dir, index_path=index_path)

    loops: list[_WorkspaceCapturingFakeLoop] = []

    def _capturing_factory():
        loop = _WorkspaceCapturingFakeLoop(steps=8, delay_s=0.01)
        loops.append(loop)
        return loop

    srv = DaemonHTTPServer(
        manager=manager,
        socket_path=socket_path,
        loop_factory=_capturing_factory,
    )
    await srv.start()

    try:
        sid = await _create_session(socket_path)

        status1, body1 = await _create_run(socket_path, sid, "goal-run1", workspace=str(ws1))
        status2, body2 = await _create_run(socket_path, sid, "goal-run2", workspace=str(ws2))
        assert status1 == 201, f"run1 创建失败: {body1}"
        assert status2 == 201, f"run2 创建失败: {body2}"
        run_id1, run_id2 = body1["run_id"], body2["run_id"]
        assert run_id1 != run_id2, "两个 run 应有不同 run_id"

        await asyncio.gather(
            _wait_run_state(socket_path, sid, run_id1, "completed", timeout=10.0),
            _wait_run_state(socket_path, sid, run_id2, "completed", timeout=10.0),
        )

        events1 = list(manager.store.replay(run_id1))
        events2 = list(manager.store.replay(run_id2))
        assert len(events1) > 0, "run1 应有事件"
        assert len(events2) > 0, "run2 应有事件"

        for rid, evts, label in [(run_id1, events1, "run1"), (run_id2, events2, "run2")]:
            completed = any(
                e.get("kind") == "state_change" and e.get("to") == "completed"
                for e in evts
            )
            assert completed, f"{label} 应有 completed state_change,实际={[e.get('kind') for e in evts]}"

        seq1 = [e["_seq"] for e in events1 if "_seq" in e]
        seq2 = [e["_seq"] for e in events2 if "_seq" in e]
        assert seq1 and seq1[0] == 1, f"run1 _seq 应从 1 开始,实际={seq1[:3]}"
        assert seq2 and seq2[0] == 1, f"run2 _seq 应从 1 开始,实际={seq2[:3]}"

        entry1 = manager.get_run(run_id1)
        entry2 = manager.get_run(run_id2)
        assert entry1 is not None and entry1.state == "completed", f"run1 index state={entry1 and entry1.state}"
        assert entry2 is not None and entry2.state == "completed", f"run2 index state={entry2 and entry2.state}"

        assert len(loops) == 2, f"应有 2 个 loop 实例,实际={len(loops)}"
        ws1_resolved = str(ws1.resolve())
        ws2_resolved = str(ws2.resolve())
        captured = {l.captured_workspace for l in loops}
        assert ws1_resolved in captured, (
            f"run1 的 runtime workspace 应是 {ws1_resolved},实际捕获={captured}"
        )
        assert ws2_resolved in captured, (
            f"run2 的 runtime workspace 应是 {ws2_resolved},实际捕获={captured}"
        )
        assert loops[0].captured_workspace != loops[1].captured_workspace, (
            f"两个并发 run 的 runtime workspace 不应相同,均为 {loops[0].captured_workspace}"
        )

    finally:
        await srv.stop()
        manager.close()




class _IdentityCapturingFakeLoop:

    def __init__(self, *, steps: int = 5, delay_s: float = 0.0,
                 captured_ids: "list[dict]", sandbox, broker, gate):
        self._steps = steps
        self._delay = delay_s
        self._captured_ids = captured_ids
        self._sandbox = sandbox
        self._broker = broker
        self._gate = gate

    async def run(self, goal: str, session_id: str):
        self._captured_ids.append({
            "sandbox_id": id(self._sandbox),
            "broker_id": id(self._broker),
            "gate_id": id(self._gate),
        })
        for i in range(self._steps):
            if self._delay:
                await asyncio.sleep(self._delay)
            yield {"kind": "token_delta", "text": f"step {i}", "step": i}
            yield {"kind": "code_action", "code": f"# step {i}", "step": i}
            yield {"kind": "code_result", "stdout": "", "value_repr": "", "exc": "", "ok": True, "step": i}
        yield {"kind": "verify_verdict", "verdict": {"status": "passed", "reason": "fake"}}


@pytest.mark.asyncio
async def test_per_run_components_are_distinct_objects(tmp_path: Path):
    import unittest.mock as mock
    from argos.daemon.server import DaemonHTTPServer
    from argos.daemon.manager import RunManager

    ws1 = tmp_path / "ws1"
    ws2 = tmp_path / "ws2"
    ws1.mkdir()
    ws2.mkdir()

    runs_dir = tmp_path / "runs"
    index_path = tmp_path / "index.json"
    socket_path = tmp_path / "daemon.sock"
    manager = RunManager(runs_dir=runs_dir, index_path=index_path)

    stub_components = mock.MagicMock()

    built_stacks: list[mock.MagicMock] = []
    captured_ids: list[dict] = []
    close_calls: list[str] = []

    def _fake_build_run_stack(c, *, workspace=None, session_id="", verify_cmd=None):
        stack = mock.MagicMock()
        stack_id = len(built_stacks)

        stub_sandbox = mock.MagicMock(name=f"sandbox_{stack_id}")
        stub_broker = mock.MagicMock(name=f"broker_{stack_id}")
        stub_gate = mock.MagicMock(name=f"gate_{stack_id}")
        stack.gate = stub_gate
        stack.sandbox = stub_sandbox
        stack.broker = stub_broker

        def _close(_sid=session_id):
            close_calls.append(_sid)
        stack.close = _close

        def _lf():
            return _IdentityCapturingFakeLoop(
                steps=5, delay_s=0.01,
                captured_ids=captured_ids,
                sandbox=stub_sandbox,
                broker=stub_broker,
                gate=stub_gate,
            )
        stack.loop_factory = _lf
        built_stacks.append(stack)
        return stack

    srv = DaemonHTTPServer(
        manager=manager,
        socket_path=socket_path,
        components=stub_components,
    )
    await srv.start()

    try:
        with mock.patch("argos.daemon.server.build_run_stack", side_effect=_fake_build_run_stack):
            sid = await _create_session(socket_path)

            status1, body1 = await _create_run(socket_path, sid, "goal-run1", workspace=str(ws1))
            status2, body2 = await _create_run(socket_path, sid, "goal-run2", workspace=str(ws2))
            assert status1 == 201, f"run1 创建失败: {body1}"
            assert status2 == 201, f"run2 创建失败: {body2}"
            run_id1, run_id2 = body1["run_id"], body2["run_id"]
            assert run_id1 != run_id2

            await asyncio.gather(
                _wait_run_state(socket_path, sid, run_id1, "completed", timeout=10.0),
                _wait_run_state(socket_path, sid, run_id2, "completed", timeout=10.0),
            )

        assert len(built_stacks) == 2, f"应有 2 个 RunStack,实际={len(built_stacks)}"

        assert len(captured_ids) == 2, f"应有 2 个 id 捕获,实际={captured_ids}"
        ids0, ids1 = captured_ids[0], captured_ids[1]
        assert ids0["sandbox_id"] != ids1["sandbox_id"], (
            f"两个并发 run 的 sandbox 不应是同一对象:"
            f" id0={ids0['sandbox_id']}, id1={ids1['sandbox_id']}"
        )
        assert ids0["broker_id"] != ids1["broker_id"], (
            f"两个并发 run 的 broker 不应是同一对象:"
            f" id0={ids0['broker_id']}, id1={ids1['broker_id']}"
        )
        assert ids0["gate_id"] != ids1["gate_id"], (
            f"两个并发 run 的 gate 不应是同一对象:"
            f" id0={ids0['gate_id']}, id1={ids1['gate_id']}"
        )

        assert len(close_calls) == 2, (
            f"两个 run 结束后各自 RunStack.close 均应被调,实际 close_calls={close_calls}"
        )

    finally:
        await srv.stop()
        manager.close()



@pytest.mark.asyncio
async def test_create_run_honest_rejection_when_no_key(server_no_key: tuple):
    srv, manager, socket_path = server_no_key
    sid = await _create_session(socket_path)

    status, raw = await _raw_req(
        socket_path, "POST", "/runs",
        session_id=sid,
        body={"goal": "should be rejected"},
    )
    assert status == 503, f"无 key 应 503,实际 {status}: {raw.decode()}"
    body = json.loads(raw.decode())
    assert body.get("code") == "no_worker_key", f"错误码应为 no_worker_key,实际={body}"
    assert "key" in body.get("message", "").lower() or "key" in str(body).lower(),\
        f"错误消息应提到 key,实际={body}"

    assert manager.list_runs() == [], "无 key 时不应创建任何 run"



def test_to_event_dict_dict_passthrough():
    from argos.daemon.worker import _to_event_dict
    d = {"kind": "token_delta", "text": "hello", "step": 0}
    result = _to_event_dict(d)
    assert result == d
    assert result is not d


def test_to_event_dict_dataclass_typed():
    from argos.daemon.worker import _to_event_dict
    from argos.protocol.events import TokenDelta
    ev = TokenDelta(text="hello")
    result = _to_event_dict(ev)
    assert result["kind"] == "token_delta"
    assert result["text"] == "hello"


def test_to_event_dict_code_action():
    from argos.daemon.worker import _to_event_dict
    from argos.protocol.events import CodeAction
    ev = CodeAction(code="print(1)", step=3)
    result = _to_event_dict(ev)
    assert result["kind"] == "code_action"
    assert result["code"] == "print(1)"
    assert result["step"] == 3


def test_daemon_approval_gate_timeout_denies():
    import asyncio
    from argos.daemon.worker import DaemonApprovalGate
    from argos.approval import ApprovalGate, ApprovalLevel, Decision

    async def _run():
        real_gate = ApprovalGate(level=ApprovalLevel.CONFIRM)
        daemon_gate = DaemonApprovalGate(real_gate, timeout_s=0.05)
        result = await daemon_gate.request(
            "run_command", {"cmd": "rm -rf /"},
            description="dangerous",
            risk="high",
        )
        assert isinstance(result, Decision), f"应返回 Decision,实际 {type(result)}"
        assert result.kind == "deny", f"超时应 deny,实际 kind={result.kind!r}"

    asyncio.run(_run())
