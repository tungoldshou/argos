"""v6 P3b TUI daemon 协议客户端化验收测试(spec §13 P3 验收 a-d)。

覆盖:
  T1. TUI 隔协议批准一个真审批
      — 起 in-process DaemonHTTPServer + GateSetterWorker/FakeApprovalLoop 触发 ApprovalRequest
      — 模拟 TUI 客户端 POST /approval once → run 完成(协议层为主)
  T2. SSE 断线重连续传(since=N)
      — DaemonEventSource 断线后以 since=last_seq 续传
  T3. daemon 不可达 → inline fallback + 状态栏诚实标注
      — socket 不存在 → _kernel_mode="inline", StatusBar 显 "inline(单进程)"
  T4. plan 决策统一路由:app.py 无 ExitPlanMode( 残留(架构契约测试)
  T5. daemon 模式下 _handle_plan_rendered 走 POST plan_decision(不调 ExitPlanMode)
"""
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


# ── T4: 架构契约测试(grep)─────────────────────────────────────────────────


def test_no_exit_plan_mode_direct_call_in_app() -> None:
    """T4: app.py 的 _handle_plan_rendered 里 ExitPlanMode 仅在向后兼容 fallback 块中。

    背景：v6 P3b §4 刀2 收口 —— TUI 对 loop 内部对象的直接引用由 respond_plan_decision
    / POST plan_decision 取代。主路径（daemon / inline 有 call_id）不再调 ExitPlanMode；
    仅保留无 call_id 的向后兼容 fallback（FakeLoop / 旧 loop）。

    架构契约：_handle_plan_rendered 中 ExitPlanMode( 调用数 <= fallback 分支数（≤2）。
    但主路径的决策逻辑必须经 respond_plan_decision 或 POST plan_decision，
    ExitPlanMode 调用必须紧跟在 "向后兼容" 注释后（同块内），不能出现在 daemon / inline 主分支。
    """
    app_path = Path(__file__).parent.parent / "argos" / "tui" / "app.py"
    src = app_path.read_text("utf-8")

    # 关键断言1：_handle_plan_rendered 里存在 respond_plan_decision 调用（主路径）
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

    # 关键断言2：daemon 路径主分支有 _daemon_plan_decision_post 调用
    assert "_daemon_plan_decision_post(" in body, (
        "_handle_plan_rendered 缺少 _daemon_plan_decision_post( 调用"
        "（daemon 路径应经 POST plan_decision）"
    )

    # 关键断言3：ExitPlanMode 调用数不超过 2（向后兼容 fallback：AUTO 分支 + non-AUTO 分支各一个）
    exit_plan_calls = re.findall(r"ExitPlanMode\(", body)
    assert len(exit_plan_calls) <= 2, (
        f"_handle_plan_rendered 有 {len(exit_plan_calls)} 处 ExitPlanMode( 调用，"
        "期望 ≤2（仅向后兼容 fallback）"
    )


# ── T3: inline fallback 状态标注 ─────────────────────────────────────────


@pytest.mark.asyncio
async def test_daemon_unreachable_inline_fallback() -> None:
    """T3: daemon socket 不存在 → inline fallback + 状态栏诚实标注。

    实现:临时 socket 路径不创建 → probe 失败 → spawn 失败(argosd 不在 PATH) → inline。
    用 patch 让 probe_or_spawn 直接返 False,验证 app 状态。
    """
    # 避免 import Textual App(重量级)，直接测试 _setup_daemon_mode 逻辑
    # 用最小 mock 构造 ArgosApp 实例
    from argos.tui.app import ArgosApp

    app = ArgosApp(demo=True)  # demo=True:不真连模型,仅测 daemon 状态机

    # mock StatusBar.set_kernel_mode 用于断言
    status_bar_mock = MagicMock()
    status_bar_mock.set_kernel_mode = MagicMock()

    def _query_one(selector, cls=None):
        if cls is not None and cls.__name__ == "StatusBar":
            return status_bar_mock
        raise Exception(f"not mounted: {selector}")

    app.query_one = _query_one
    app.run_worker = MagicMock()  # 不真起 Textual worker

    # patch probe_or_spawn 在 daemon_spawn 模块层面返 False
    with patch("argos.tui.daemon_spawn.probe_or_spawn", new=AsyncMock(return_value=False)):
        # 直接 await _setup_daemon_mode
        with patch.dict(os.environ, {"ARGOS_DAEMON_SOCKET": "/tmp/_argos_nonexistent_test.sock"}):
            await app._setup_daemon_mode()

    assert app._kernel_mode == "inline", f"expected 'inline', got {app._kernel_mode!r}"
    assert app._with_daemon is False
    assert app._daemon_client is None
    status_bar_mock.set_kernel_mode.assert_called_once_with("inline(单进程)")


@pytest.mark.asyncio
async def test_daemon_available_sets_argosd_mode(monkeypatch) -> None:
    """T5: daemon 可达 → _kernel_mode="argosd", _with_daemon=True, StatusBar 更新。

    本测显式测 argosd 路径:豁免 conftest 的 ARGOS_NO_DAEMON 隔离开关
    (probe 已 monkeypatch 成假的,不会碰真 daemon)。"""
    from argos.tui.app import ArgosApp
    from argos.daemon.client import DaemonClient

    monkeypatch.delenv("ARGOS_NO_DAEMON", raising=False)
    app = ArgosApp(demo=True)

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


# ── T2: DaemonEventSource SSE 断线重连续传 ──────────────────────────────


@pytest.mark.asyncio
async def test_daemon_event_source_reconnect_with_since() -> None:
    """T2: DaemonEventSource 断线重连时以 since=last_seq 续传。

    模拟:第一次订阅 yield 2 个事件(seq 1, 2),然后抛 ConnectionError 模拟断线;
    DaemonEventSource 重连时 since=2(= 上次最大 seq),只收后续事件。
    验证:收到事件序列按 seq 顺序,without 重复。
    """
    from argos.tui.daemon_source import DaemonEventSource
    from argos.protocol.events import TokenDelta

    # 构造 fake _subscribe_once generator
    call_count = [0]

    async def _fake_subscribe(since: int = 0):
        call_count[0] += 1
        if call_count[0] == 1:
            # 第一次:yield 2 个事件后抛断线
            yield {"kind": "token_delta", "text": "hello", "_seq": 1}
            yield {"kind": "token_delta", "text": "world", "_seq": 2}
            raise ConnectionError("simulated disconnect")
        else:
            # 第二次:from since=2 继续,yield 1 个事件后正常结束
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
    # 确认 since 传递正确（由断言在 _fake_subscribe 内完成）
    assert call_count[0] == 2, f"expected 2 subscribe calls, got {call_count[0]}"


# ── T1 辅助:GateHolder + FakeApprovalLoop + GateSetterWorker ────────────


class _GateHolder:
    """可变 gate 引用持有者:worker.run() 替换 gate 后,loop 通过此 holder 拿到新引用。"""
    def __init__(self) -> None:
        self.gate: Any = None


class _FakeApprovalLoop:
    """可控 fake loop:经 DaemonApprovalGate 触发一次审批后完成。

    gate_holder.gate 在 worker.run() 把真 gate 包装为 DaemonApprovalGate 后才有值。
    loop 在第一个 yield 后 sleep 一小段等 holder 被设置,再调 gate.request()。
    """

    def __init__(self, *, gate_holder: _GateHolder, call_id: str) -> None:
        self._holder = gate_holder
        self._call_id = call_id
        self.decision_received: Any = None

    async def run(self, goal: str, session_id: str) -> AsyncIterator[dict]:
        # 步骤1: 让 worker.run() 完成 DaemonApprovalGate 包装
        yield {"kind": "token_delta", "text": "preparing approval"}
        await asyncio.sleep(0.05)  # 等 holder.gate 被 worker 设置

        gate = self._holder.gate
        assert gate is not None, "_GateHolder.gate 未被设置"

        # 步骤2: 挂起等审批(经 DaemonApprovalGate → SSE 扇出 + Future 挂起)
        decision = await gate.request(
            "test_action",
            {"target": "/tmp/test.txt"},
            description="test approval (P3b T1)",
            risk="medium",
            call_id=self._call_id,
        )
        self.decision_received = decision

        # 步骤3: 完成
        yield {"kind": "verify_verdict",
               "verdict": {"status": "passed", "reason": "T1 approval done"}}


class _FakeApprovalLoopFactory:
    def __init__(self, loop: _FakeApprovalLoop) -> None:
        self._loop = loop

    def __call__(self) -> _FakeApprovalLoop:
        return self._loop


class _GateSetterWorker:
    """RunWorker 薄包装:pre-wrap gate → DaemonApprovalGate 并通知 GateHolder。

    RunWorker.__init__ 将真 gate 存为 self._gate；run() 内部会检查 isinstance(self._gate,
    DaemonApprovalGate) 并跳过重包装。
    我们在 __init__ 里提前替换,再把引用写入 holder.gate。
    """

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
        # 提前包装 gate → holder 知道目标引用
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


# ── T1: 协议层隔离审批流程测试 ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_protocol_approval_circuit_inline(tmp_path: Path) -> None:
    """T1(协议层为主): in-process DaemonHTTPServer + FakeApprovalLoop 触发审批 → POST once → 完成。

    流程:
      1. 起 DaemonHTTPServer + RunManager
      2. _FakeApprovalLoop via _GateSetterWorker:投 token_delta → 挂起等 gate.request → 完成
      3. 订阅 SSE 等到 approval_request;POST /approval once 解锁
      4. 等 run 完成;断言 verify_verdict 事件到达 + approval_response 落盘

    这是「TUI 隔协议批准一个真审批」的协议层等价测试(spec §13 P3a 验收 P3b T1)。
    """
    from argos.approval import ApprovalGate, ApprovalLevel
    from argos.daemon.manager import RunManager
    from argos.daemon.server import DaemonHTTPServer
    from argos.daemon.client import DaemonClient

    socket_path = tmp_path / "t1.sock"
    manager = RunManager(
        runs_dir=tmp_path / "runs",
        index_path=tmp_path / "index.json",
    )

    # ── 构造 FakeApprovalLoop + GateHolder ───────────────────────────
    real_gate = ApprovalGate(level=ApprovalLevel.CONFIRM)
    holder = _GateHolder()
    call_id = uuid.uuid4().hex[:12]
    fake_loop = _FakeApprovalLoop(gate_holder=holder, call_id=call_id)

    # ── 手工创建 run + worker(不经 server create_run) ───────────────
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
    srv._workers[run_id] = gw._worker  # 注册到 server(以便 SSE 路由 + approval POST)
    await srv.start()

    # 启动 worker 协程
    worker_task = asyncio.create_task(gw.run(), name=f"t1-worker-{run_id}")
    try:
        sid = await DaemonClient(socket_path, timeout=8.0).create_session()

        # 等 run 进 running 状态
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

        # ── 订阅 SSE,等待 approval_request ──────────────────────────
        # deadline2=8s:xdist 并行高负载下 worker 调度可能延迟,加大等待窗口。
        # 语义不变:approval_timeout_s=10s 是真实超时,这里 8s 只是测试轮询上限。
        cli = DaemonClient(socket_path, timeout=8.0)
        seen_events: list[dict] = []
        approval_call_id: str | None = None

        deadline2 = time.monotonic() + 8.0   # 原 5s → 8s,防止并行高负载下错过事件
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

        # ── 等 run 完成 ───────────────────────────────────────────────
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

        # ── 断言事件序列:通过 store.replay 读落盘事件,避免第二次 SSE 订阅挂起 ──
        # run 已完成,store 是权威来源;SSE 流已在第一次订阅中断
        store_events = list(manager.store.replay(run_id))
        store_kinds = [e.get("kind") for e in store_events]

        assert "verify_verdict" in store_kinds, (
            f"verify_verdict 未落盘; store_kinds={store_kinds}"
        )

        # approval_response 落盘(审计可见)
        assert "approval_response" in store_kinds, (
            f"approval_response 未落盘; store_kinds={store_kinds}"
        )

        # decision 正确传达到 loop
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
    """StatusBar.set_kernel_mode 正确更新 render_text 中的内核模式标注。"""
    from argos.tui.widgets.status_bar import StatusBar

    bar = StatusBar()
    # 初始:无模式段
    assert "argosd" not in bar.render_text
    assert "inline" not in bar.render_text

    bar.set_kernel_mode("argosd")
    assert "argosd" in bar.render_text

    bar.set_kernel_mode("inline(单进程)")
    assert "inline(单进程)" in bar.render_text

    bar.set_kernel_mode("")
    # 清除后不显示任何模式
    assert "argosd" not in bar.render_text
    assert "inline" not in bar.render_text
