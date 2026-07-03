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
    proj = tmp_path / "proj"
    proj.mkdir()
    monkeypatch.setenv("ARGOS_WORKSPACE", str(proj))
    tok = runtime.use_project(str(proj))
    yield proj
    runtime.reset(tok)


@pytest.fixture
def build_real_loop(store, in_project, requires_sandbox):
    created: list = []

    def _make(scripts, *, verify_cmd=None, level=ApprovalLevel.AUTO, max_rounds=3, gated=False):
        gate = ApprovalGate(level=level)
        broker = CapabilityBroker(
            gate=gate,
            egress=EgressPolicy(llm_hosts=set(), search_hosts=set(), mcp_hosts=set()),
            signer=ReceiptSigner(key=b"e2e-key"),
        )

        if gated:
            def broker_handler(action, args):
                return broker.request_blocking(action, args)
        else:
            def broker_handler(action, args):
                value, _exit = broker._execute(action, args)
                return value

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
    return [ev async for ev in loop.run(goal, session_id)]
