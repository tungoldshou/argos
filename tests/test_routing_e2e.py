import json
from pathlib import Path

import httpx
import pytest

from argos.approval import ApprovalLevel
from argos.core.loop import AgentLoop, LoopConfig
from argos.core.models import CredentialPool, ModelClient, ModelTier
from argos.routing.categorizer import TaskCategory
from argos.routing.config import RoutingConfig
from argos.routing.router import ModelRouter
from argos.tui.events import (
    CostUpdate, EventBus, VerifyVerdict,
)


def _sse_transport(text_pieces: list[str]) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        lines = []
        for piece in text_pieces:
            data = {"type": "content_block_delta", "delta": {"type": "text_delta", "text": piece}}
            lines.append(f"event: content_block_delta\ndata: {json.dumps(data)}\n")
        lines.append('event: message_stop\ndata: {"type":"message_stop"}\n')
        body = "\n".join(lines)
        return httpx.Response(200, text=body, headers={"content-type": "text/event-stream"})
    return httpx.MockTransport(handler)


def _client(name: str, text: str) -> ModelClient:
    tier = ModelTier(name=name, model=f"{name}-model",
                     base_url="https://x/anthropic", max_tokens=4096)
    return ModelClient(tier=tier, pool=CredentialPool(["k"]), transport=_sse_transport([text]))


def test_e2e_router_routes_three_tiers_and_tracks_decisions():
    routing = RoutingConfig(
        default="default",
        by_category={"file_edit": "cheap", "verify": "strong"},
        tier_force_confirm=["strong"],
    )
    clients = {
        "cheap": _client("cheap", "ok"),
        "default": _client("default", "ok"),
        "strong": _client("strong", "ok"),
    }

    def factory(name: str) -> ModelClient:
        return clients.get(name) or _client(name, "ok")

    router = ModelRouter(routing=routing, client_factory=factory)

    c1, d1 = router.select(category=TaskCategory.FILE_EDIT, tool="edit_file", step=0)
    assert d1.tier == "cheap"
    assert d1.source == "by_category"
    assert c1.tier.name == "cheap"

    # verify → strong
    c2, d2 = router.select(category=TaskCategory.VERIFY, tool="run_command", step=1)
    assert d2.tier == "strong"
    assert d2.source == "by_category"
    assert c2.tier.name == "strong"

    # plan → default
    c3, d3 = router.select(category=TaskCategory.PLAN, tool=None, step=2)
    assert d3.tier == "default"
    assert d3.source == "default"

    hist = router.history()
    assert len(hist) == 3
    assert [h.tier for h in hist] == ["cheap", "strong", "default"]


def test_e2e_router_is_force_confirm_for_strong():
    routing = RoutingConfig(
        default="default", by_category={"verify": "strong"},
        tier_force_confirm=["strong"],
    )
    router = ModelRouter(routing=routing, client_factory=lambda n: _client(n, "ok"))
    _, decision = router.select(category=TaskCategory.VERIFY, tool=None, step=0)
    assert routing.is_force_confirm(decision.tier) is True


def test_e2e_router_cheap_not_force_confirm():
    routing = RoutingConfig(
        default="default", by_category={"file_edit": "cheap"},
        tier_force_confirm=["strong"],
    )
    assert routing.is_force_confirm("cheap") is False
    assert routing.is_force_confirm("default") is False


def test_e2e_run_uses_router_loop_state():
    import tempfile
    from argos.core.verify_gate import Verifier
    from argos.memory.store import ArgosStore
    from argos.sandbox.broker import CapabilityBroker
    from argos.sandbox.egress import EgressPolicy
    from argos.sandbox.executor import SeatbeltExecutor
    from argos.tools.receipts import ReceiptSigner

    with tempfile.TemporaryDirectory() as td:
        ws = Path(td) / "ws"
        ws.mkdir()
        db = Path(td) / "a.db"
        store = ArgosStore(db_path=str(db))
        signer = ReceiptSigner(key=b"e2e-routing")
        routing = RoutingConfig(
            default="default",
            by_category={"file_edit": "cheap"},
            tier_force_confirm=["strong"],
        )
        router = ModelRouter(routing=routing, client_factory=lambda n: _client(n, "ok"))
        model = _client("default", "ok")
        cfg = LoopConfig(model_tier="default", verify_cmd=None, max_steps=2, max_rounds=1,
                         approval_level=ApprovalLevel.AUTO, compaction=False)
        sandbox = SeatbeltExecutor(broker_handler=lambda a, b: None)
        broker = CapabilityBroker(
            gate=None, egress=EgressPolicy(llm_hosts=set(), search_hosts=set(), mcp_hosts=set()),
            signer=signer, workspace=ws,
        )
        loop = AgentLoop(
            store=store, bus=EventBus(), sandbox=sandbox, broker=broker, model=model,
            verifier=Verifier(max_rounds=1), config=cfg, workspace=ws, verify_dir=ws,
            router=router,
        )
        assert loop._current_tier == "default"
        assert loop._router is router


def test_e2e_run_emits_cost_update_tier_name():
    import asyncio
    import tempfile
    from argos.core.verify_gate import Verifier
    from argos.memory.store import ArgosStore
    from argos.sandbox.broker import CapabilityBroker
    from argos.sandbox.egress import EgressPolicy
    from argos.sandbox.executor import SeatbeltExecutor
    from argos.tools.receipts import ReceiptSigner

    class _ScriptedModel:
        def __init__(self) -> None:
            self.tier = ModelTier(name="default", model="m", base_url="https://x/a",
                                  max_tokens=4096)
            self.last_usage = {"input_tokens": 1, "output_tokens": 1,
                               "cache_read": 0, "cache_creation": 0}

        async def stream(self, messages, *, system, system_dynamic=None):
            yield "```python\n"
            yield "edit_file('a.py', 'old', 'new', all_occurrences=False)\n"
            yield "```\n"
            yield "完成。"

        async def complete(self, messages, *, system) -> str:
            return "ok"

    with tempfile.TemporaryDirectory() as td:
        ws = Path(td) / "ws"
        ws.mkdir()
        db = Path(td) / "a.db"
        store = ArgosStore(db_path=str(db))
        signer = ReceiptSigner(key=b"e2e-tname")
        routing = RoutingConfig(
            default="default", by_category={"file_edit": "cheap"},
            tier_force_confirm=["strong"],
        )
        router = ModelRouter(routing=routing, client_factory=lambda n: _client(n, "ok"))
        cfg = LoopConfig(model_tier="default", verify_cmd=None, max_steps=4, max_rounds=1,
                         approval_level=ApprovalLevel.AUTO, compaction=False)
        sandbox = SeatbeltExecutor(broker_handler=lambda a, b: None)
        broker = CapabilityBroker(
            gate=None, egress=EgressPolicy(llm_hosts=set(), search_hosts=set(), mcp_hosts=set()),
            signer=signer, workspace=ws,
        )
        model = _ScriptedModel()
        loop = AgentLoop(
            store=store, bus=EventBus(), sandbox=sandbox, broker=broker, model=model,
            verifier=Verifier(max_rounds=1), config=cfg, workspace=ws, verify_dir=ws,
            router=router,
        )

        async def _go():
            costs: list[str] = []
            async for ev in loop.run("改 a.py 的 old 为 new", "e2e-sess"):
                if isinstance(ev, CostUpdate):
                    costs.append(ev.tier_name)
            return costs

        assert loop._router is router
        assert loop._current_tier == "default"
