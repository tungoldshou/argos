from __future__ import annotations

import asyncio
import json
import os
import re
import socket
import tempfile
import time
import uuid
from pathlib import Path
from typing import Any, AsyncIterator
from unittest.mock import AsyncMock, MagicMock, patch

import pytest




def test_no_exit_plan_mode_direct_call_in_app() -> None:
    app_path = Path(__file__).parent.parent / "argos" / "tui" / "app.py"
    src = app_path.read_text("utf-8")

    start = src.find("async def _handle_plan_rendered(")
    assert start != -1, "找不到 _handle_plan_rendered 方法"
    end = src.find("\n    async def ", start + 1)
    if end == -1:
        end = len(src)
    body = src[start:end]

    assert "respond_plan_decision(" in body, (
        "_handle_plan_rendered 缺少 respond_plan_decision( 调用"
        "（主路径应经 loop.respond_plan_decision 回传决策）"
    )

    assert "_daemon_plan_decision_post(" in body, (
        "_handle_plan_rendered 缺少 _daemon_plan_decision_post( 调用"
        "（daemon 路径应经 POST plan_decision）"
    )

    exit_plan_calls = re.findall(r"ExitPlanMode\(", body)
    assert len(exit_plan_calls) <= 2, (
        f"_handle_plan_rendered 有 {len(exit_plan_calls)} 处 ExitPlanMode( 调用，"
        "期望 ≤2（仅向后兼容 fallback）"
    )




@pytest.mark.asyncio
async def test_daemon_unreachable_inline_fallback(monkeypatch) -> None:
    from argos.tui.app import ArgosApp

    app = ArgosApp()

    status_bar_mock = MagicMock()
    status_bar_mock.set_kernel_mode = MagicMock()

    transcript_mock = MagicMock()
    transcript_mock.append_line = MagicMock(return_value=object())

    def _query_one(selector, cls=None):
        if cls is not None and cls.__name__ == "StatusBar":
            return status_bar_mock
        if selector == "#transcript":
            return transcript_mock
        raise Exception(f"not mounted: {selector}")

    app.query_one = _query_one
    app.run_worker = MagicMock()
    monkeypatch.delenv("ARGOS_NO_DAEMON", raising=False)

    with patch("argos.tui.daemon_spawn.probe_or_spawn", new=AsyncMock(return_value=False)):
        with patch.dict(os.environ, {"ARGOS_DAEMON_SOCKET": "/tmp/_argos_nonexistent_test.sock"}):
            await app._setup_daemon_mode()

    assert app._kernel_mode == "inline", f"expected 'inline', got {app._kernel_mode!r}"
    assert app._with_daemon is False
    assert app._daemon_client is None
    status_bar_mock.set_kernel_mode.assert_called_once_with("inline(单进程)")
    transcript_mock.append_line.assert_called_once()
    assert transcript_mock.append_line.call_args.kwargs["kind"] == "error"


@pytest.mark.asyncio
async def test_daemon_socket_path_honors_env_local_config(tmp_path, monkeypatch) -> None:
    from argos import config as C
    from argos.tui.app import ArgosApp

    app = ArgosApp()
    status_bar_mock = MagicMock()
    transcript_mock = MagicMock()
    transcript_mock.append_line = MagicMock(return_value=object())

    def _query_one(selector, cls=None):
        if cls is not None and cls.__name__ == "StatusBar":
            return status_bar_mock
        if selector == "#transcript":
            return transcript_mock
        raise Exception(f"not mounted: {selector}")

    socket_path = tmp_path / "from-env-local.sock"
    app.query_one = _query_one
    app.run_worker = MagicMock()
    monkeypatch.delenv("ARGOS_NO_DAEMON", raising=False)
    monkeypatch.delenv("ARGOS_DAEMON_SOCKET", raising=False)
    monkeypatch.setattr(C, "_ENV", {"ARGOS_DAEMON_SOCKET": str(socket_path)})

    probe = AsyncMock(return_value=False)
    with patch("argos.tui.daemon_spawn.probe_or_spawn", new=probe):
        await app._setup_daemon_mode()

    probe.assert_awaited_once_with(socket_path)


@pytest.mark.asyncio
async def test_daemon_socket_path_defaults_to_argos_config_dir(tmp_path, monkeypatch) -> None:
    from unittest.mock import AsyncMock, patch
    from argos import config as C
    from argos.tui.app import ArgosApp

    cfg_dir = tmp_path / "cfg"
    socket_path = cfg_dir / "daemon.sock"
    monkeypatch.setenv("ARGOS_CONFIG_DIR", str(cfg_dir))
    monkeypatch.delenv("ARGOS_DAEMON_SOCKET", raising=False)
    monkeypatch.setattr(C, "_ENV", {})

    app = ArgosApp()
    status_bar_mock = MagicMock()
    transcript_mock = MagicMock()
    transcript_mock.append_line = MagicMock(return_value=object())

    def _query_one(selector, cls=None):
        if cls is not None and cls.__name__ == "StatusBar":
            return status_bar_mock
        if selector == "#transcript":
            return transcript_mock
        raise Exception(f"not mounted: {selector}")

    app.query_one = _query_one
    app.run_worker = MagicMock()
    monkeypatch.delenv("ARGOS_NO_DAEMON", raising=False)
    probe = AsyncMock(return_value=False)

    with patch("argos.tui.daemon_spawn.probe_or_spawn", new=probe):
        await app._setup_daemon_mode()

    probe.assert_awaited_once_with(socket_path)


@pytest.mark.asyncio
async def test_daemon_available_sets_argosd_mode(monkeypatch) -> None:
    from argos.tui.app import ArgosApp
    from argos.daemon.client import DaemonClient

    monkeypatch.delenv("ARGOS_NO_DAEMON", raising=False)
    app = ArgosApp()

    status_bar_mock = MagicMock()
    status_bar_mock.set_kernel_mode = MagicMock()

    def _query_one(selector, cls=None):
        if cls is not None and cls.__name__ == "StatusBar":
            return status_bar_mock
        raise Exception(f"not mounted: {selector}")

    app.query_one = _query_one
    app.run_worker = MagicMock()

    fake_session_id = "sess-abc123"

    with patch("argos.tui.daemon_spawn.probe_or_spawn", new=AsyncMock(return_value=True)):
        with patch.object(DaemonClient, "create_session", new=AsyncMock(return_value=fake_session_id)):
            with patch.dict(os.environ, {"ARGOS_DAEMON_SOCKET": "/tmp/_argos_test_daemon.sock"}):
                await app._setup_daemon_mode()

    assert app._kernel_mode == "argosd", f"expected 'argosd', got {app._kernel_mode!r}"
    assert app._with_daemon is True
    assert app._daemon_session_id == fake_session_id
    status_bar_mock.set_kernel_mode.assert_called_once_with("argosd")


@pytest.mark.asyncio
async def test_daemon_session_create_failure_reports_error_lane(monkeypatch) -> None:
    from argos.daemon.client import DaemonClient
    from argos.tui.app import ArgosApp

    app = ArgosApp()
    status_bar_mock = MagicMock()
    transcript_mock = MagicMock()
    transcript_mock.append_line = MagicMock(return_value=object())

    def _query_one(selector, cls=None):
        if cls is not None and cls.__name__ == "StatusBar":
            return status_bar_mock
        if selector == "#transcript":
            return transcript_mock
        raise Exception(f"not mounted: {selector}")

    app.query_one = _query_one
    app.run_worker = MagicMock()
    monkeypatch.delenv("ARGOS_NO_DAEMON", raising=False)

    with patch("argos.tui.daemon_spawn.probe_or_spawn", new=AsyncMock(return_value=True)):
        with patch.object(DaemonClient, "create_session", new=AsyncMock(side_effect=OSError("boom"))):
            with patch.dict(os.environ, {"ARGOS_DAEMON_SOCKET": "/tmp/_argos_test_daemon.sock"}):
                await app._setup_daemon_mode()

    assert app._kernel_mode == "inline"
    assert app._with_daemon is False
    transcript_mock.append_line.assert_called_once()
    assert transcript_mock.append_line.call_args.kwargs["kind"] == "error"




@pytest.mark.asyncio
async def test_daemon_event_source_reconnect_with_since() -> None:
    from argos.tui.daemon_source import DaemonEventSource
    from argos.protocol.events import TokenDelta

    call_count = [0]

    async def _fake_subscribe(since: int = 0):
        call_count[0] += 1
        if call_count[0] == 1:
            yield {"kind": "token_delta", "text": "hello", "_seq": 1}
            yield {"kind": "token_delta", "text": "world", "_seq": 2}
            raise ConnectionError("simulated disconnect")
        else:
            assert since == 2, f"since should be 2, got {since}"
            yield {"kind": "token_delta", "text": "reconnected", "_seq": 3}
            return

    source = DaemonEventSource(
        Path("/tmp/_fake.sock"), "run-test", "sess-test",
        max_retries=3,
    )
    source._subscribe_once = _fake_subscribe  # type: ignore[method-assign]

    collected = []
    async for ev in source.stream():
        collected.append(ev)

    assert len(collected) == 3, f"expected 3 events, got {len(collected)}: {collected}"
    assert isinstance(collected[0], TokenDelta)
    assert collected[0].text == "hello"
    assert collected[1].text == "world"
    assert collected[2].text == "reconnected"
    assert call_count[0] == 2, f"expected 2 subscribe calls, got {call_count[0]}"




class _GateHolder:
    def __init__(self) -> None:
        self.gate: Any = None


class _FakeApprovalLoop:

    def __init__(self, *, gate_holder: _GateHolder, call_id: str) -> None:
        self._holder = gate_holder
        self._call_id = call_id
        self.decision_received: Any = None

    async def run(self, goal: str, session_id: str) -> AsyncIterator[dict]:
        yield {"kind": "token_delta", "text": "preparing approval"}
        await asyncio.sleep(0.05)

        gate = self._holder.gate
        assert gate is not None, "_GateHolder.gate 未被设置"

        decision = await gate.request(
            "test_action",
            {"target": "/tmp/test.txt"},
            description="test approval (P3b T1)",
            risk="medium",
            call_id=self._call_id,
        )
        self.decision_received = decision

        yield {"kind": "verify_verdict",
               "verdict": {"status": "passed", "reason": "T1 approval done"}}


class _FakeApprovalLoopFactory:
    def __init__(self, loop: _FakeApprovalLoop) -> None:
        self._loop = loop

    def __call__(self) -> _FakeApprovalLoop:
        return self._loop


class _GateSetterWorker:

    def __init__(
        self,
        run_id: str,
        manager: Any,
        loop_factory: Any,
        gate: Any,
        approval_timeout_s: float,
        gate_holder: _GateHolder,
    ) -> None:
        from argos.daemon.worker import RunWorker, DaemonApprovalGate
        self._worker = RunWorker(
            run_id=run_id,
            manager=manager,
            loop_factory=loop_factory,
            gate=gate,
            approval_timeout_s=approval_timeout_s,
        )
        if (self._worker._gate is not None
                and not isinstance(self._worker._gate, DaemonApprovalGate)):
            wrapped = DaemonApprovalGate(
                self._worker._gate,
                timeout_s=approval_timeout_s,
                run_id=run_id,
                manager=manager,
            )
            self._worker._gate = wrapped
        gate_holder.gate = self._worker._gate

    async def run(self) -> None:
        await self._worker.run()

    @property
    def run_id(self) -> str:
        return self._worker.run_id




@pytest.mark.asyncio
async def test_protocol_approval_circuit_inline(tmp_path: Path) -> None:
    from argos.approval import ApprovalGate, ApprovalLevel
    from argos.daemon.manager import RunManager
    from argos.daemon.server import DaemonHTTPServer
    from argos.daemon.client import DaemonClient

    socket_path = tmp_path / "t1.sock"
    manager = RunManager(
        runs_dir=tmp_path / "runs",
        index_path=tmp_path / "index.json",
    )

    real_gate = ApprovalGate(level=ApprovalLevel.CONFIRM)
    holder = _GateHolder()
    call_id = uuid.uuid4().hex[:12]
    fake_loop = _FakeApprovalLoop(gate_holder=holder, call_id=call_id)

    run_id = await manager.create_run(goal="T1 approval test", workspace=str(tmp_path))
    gw = _GateSetterWorker(
        run_id=run_id,
        manager=manager,
        loop_factory=_FakeApprovalLoopFactory(fake_loop),
        gate=real_gate,
        approval_timeout_s=10.0,
        gate_holder=holder,
    )

    srv = DaemonHTTPServer(manager=manager, socket_path=socket_path)
    srv._workers[run_id] = gw._worker
    await srv.start()

    worker_task = asyncio.create_task(gw.run(), name=f"t1-worker-{run_id}")
    try:
        sid = await DaemonClient(socket_path, timeout=8.0).create_session()

        deadline = time.monotonic() + 3.0
        while time.monotonic() < deadline:
            entry = manager.get_run(run_id)
            if entry is not None and entry.state == "running":
                break
            await asyncio.sleep(0.02)
        entry = manager.get_run(run_id)
        assert entry is not None and entry.state == "running", (
            f"run 未进入 running,state={entry.state if entry else 'None'}"
        )

        cli = DaemonClient(socket_path, timeout=8.0)
        seen_events: list[dict] = []
        approval_call_id: str | None = None

        deadline2 = time.monotonic() + 8.0
        async for ev in cli.subscribe_events(run_id, sid):
            seen_events.append(ev)
            if ev.get("kind") == "approval_request":
                approval_call_id = ev.get("call_id")
                break
            if time.monotonic() > deadline2:
                break

        assert approval_call_id is not None, (
            f"approval_request 未出现; 已收: {[e.get('kind') for e in seen_events]}"
        )
        assert approval_call_id == call_id

        # ── POST /approval once ──────────────────────────────────────
        status, _, raw = await cli._request(
            "POST", f"/runs/{run_id}/approval/{approval_call_id}",
            session_id=sid,
            body={"decision": "once"},
        )
        assert status == 200, raw.decode()
        resp = json.loads(raw.decode())
        assert resp["decision"] == "once"

        deadline3 = time.monotonic() + 5.0
        while time.monotonic() < deadline3:
            entry = manager.get_run(run_id)
            if entry is not None and entry.state == "completed":
                break
            await asyncio.sleep(0.02)
        entry = manager.get_run(run_id)
        assert entry is not None and entry.state == "completed", (
            f"run 未完成,state={entry.state if entry else 'None'}"
        )

        store_events = list(manager.store.replay(run_id))
        store_kinds = [e.get("kind") for e in store_events]

        assert "verify_verdict" in store_kinds, (
            f"verify_verdict 未落盘; store_kinds={store_kinds}"
        )

        assert "approval_response" in store_kinds, (
            f"approval_response 未落盘; store_kinds={store_kinds}"
        )

        assert fake_loop.decision_received is not None
        assert fake_loop.decision_received.approved is True

    finally:
        worker_task.cancel()
        try:
            await asyncio.wait_for(worker_task, timeout=2.0)
        except (asyncio.CancelledError, asyncio.TimeoutError):
            pass
        await srv.stop()


# ── Status bar kernel_mode label test ───────────────────────────────────


def test_status_bar_kernel_mode_label() -> None:
    from argos.tui.widgets.status_bar import StatusBar

    bar = StatusBar()
    assert "argosd" not in bar.render_text
    assert "inline" not in bar.render_text

    bar.set_kernel_mode("argosd")
    assert "argosd" in bar.render_text

    bar.set_kernel_mode("inline(单进程)")
    assert "inline(单进程)" in bar.render_text

    bar.set_kernel_mode("")
    assert "argosd" not in bar.render_text
    assert "inline" not in bar.render_text
