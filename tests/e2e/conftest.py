"""e2e 共享 fixture:tmp ArgosStore、in_project、build_real_loop(真栈 + ScriptedModelClient)。

接线对齐 canonical(tests/test_e2e_loop_sandbox.py 范本):
  · 沙箱 = SeatbeltExecutor(broker_handler 同步桥),不预 spawn —— loop.run() 自己 spawn/close。
  · EgressPolicy(*, llm_hosts, search_hosts, mcp_hosts)(无 from_config)。
  · in_project 设 ARGOS_WORKSPACE env(子进程 files.py 模块级 WORKSPACE 据此解析)。
  · workspace=verify_dir=项目目录,传给 AgentLoop(项目模式)。
"""
from __future__ import annotations

import pytest

from argos import runtime
from argos.approval import ApprovalGate, ApprovalLevel
from argos.core.loop import AgentLoop, LoopConfig
from argos.core.verify_gate import Verifier
from argos.memory.store import ArgosStore
from argos.sandbox.broker import CapabilityBroker
from argos.sandbox.egress import EgressPolicy
from argos.sandbox.executor import select_backend
from argos.tools.receipts import ReceiptSigner
from argos.tui.events import EventBus

from tests.e2e.scripted_model import ScriptedModelClient


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setenv("ARGOS_DB_PATH", str(tmp_path / "argos.db"))
    s = ArgosStore(db_path=str(tmp_path / "argos.db"))
    yield s
    s.close()


@pytest.fixture
def in_project(tmp_path, monkeypatch):
    """切到 tmp 项目目录(workspace=verify_dir=该目录,project 模式),沿用现 runtime API。
    设 ARGOS_WORKSPACE 让沙箱子进程 files.py 把 write_file 落到该目录。"""
    proj = tmp_path / "proj"
    proj.mkdir()
    monkeypatch.setenv("ARGOS_WORKSPACE", str(proj))
    tok = runtime.use_project(str(proj))
    yield proj
    runtime.reset(tok)


@pytest.fixture
def build_real_loop(store, in_project, requires_sandbox):
    """工厂:给定脚本 + verify_cmd + approval_level → 真栈 AgentLoop(只换 model 为脚本替身)。

    沙箱不预 spawn:loop.run() 在开头 spawn、finally close(loop.py)。teardown 兜底 close(幂等)。

    requires_sandbox 依赖:无沙箱后端的平台(mac 缺 sandbox-exec、Linux 缺 bwrap/unshare)
    直接 skip,绝不 mock 把沙箱测试假跑过。
    """
    created: list = []

    def _make(scripts, *, verify_cmd=None, level=ApprovalLevel.AUTO, max_rounds=3):
        gate = ApprovalGate(level=level)
        broker = CapabilityBroker(
            gate=gate,
            egress=EgressPolicy(llm_hosts=set(), search_hosts=set(), mcp_hosts=set()),
            signer=ReceiptSigner(key=b"e2e-key"),
        )

        # 同步 broker_handler 桥(exec_code 阻塞等 broker_reply;AUTO 档直接 _execute)。
        def broker_handler(action, args):
            value, _exit = broker._execute(action, args)
            return value

        # 平台感知:macOS → Seatbelt,Linux → bwrap/unshare。
        sandbox = select_backend()(broker_handler=broker_handler)
        model = ScriptedModelClient(scripts)
        verifier = Verifier(max_rounds=max_rounds)
        cfg = LoopConfig(model_tier="worker", verify_cmd=verify_cmd, max_rounds=max_rounds,
                         max_steps=40, compaction=False, approval_level=level)
        loop = AgentLoop(store=store, bus=EventBus(), sandbox=sandbox, broker=broker,
                         model=model, verifier=verifier, config=cfg,
                         workspace=in_project, verify_dir=in_project)
        created.append((loop, sandbox))
        return loop

    yield _make
    for _loop, sandbox in created:
        sandbox.close()


async def drain(loop, goal: str, session_id: str) -> list:
    """跑一轮 run,收齐所有 Event(契约 §3 AgentLoop.run 返回 AsyncIterator[Event])。"""
    return [ev async for ev in loop.run(goal, session_id)]
