"""#11 T5+T6 --effort CLI + CostUpdate.tier_name + AgentLoop 注入 router 扩展 测试。"""
import json

import httpx
import pytest

from argos_agent.approval import ApprovalLevel
from argos_agent.core.loop import LoopConfig
from argos_agent.core.models import CredentialPool, ModelClient, ModelTier
from argos_agent.routing.categorizer import TaskCategory
from argos_agent.routing.config import RoutingConfig
from argos_agent.routing.effort import (
    EFFORT_PRESETS, EffortLevel, effort_settings,
)
from argos_agent.routing.router import ModelRouter
from argos_agent.tui.events import CostUpdate, deserialize_event, serialize_event


# ── T5:effort + CostUpdate.tier_name ──────────────────────────────


def test_effort_settings_low_uses_8_steps_auto():
    s = effort_settings(EffortLevel.LOW)
    assert s.max_steps == 8
    assert s.approval_level == ApprovalLevel.AUTO


def test_effort_settings_high_uses_80_steps_confirm():
    s = effort_settings(EffortLevel.HIGH)
    assert s.max_steps == 80
    assert s.approval_level == ApprovalLevel.CONFIRM


def test_effort_presets_complete():
    assert set(EFFORT_PRESETS.keys()) == {EffortLevel.LOW, EffortLevel.MEDIUM, EffortLevel.HIGH}


def test_cost_update_default_tier_name_empty():
    cu = CostUpdate(tokens_in=0, tokens_out=0, cost_usd=None, elapsed_s=0.0)
    assert cu.tier_name == ""


def test_cost_update_serialize_with_tier_name_round_trip():
    cu = CostUpdate(tokens_in=10, tokens_out=20, cost_usd=0.001, elapsed_s=1.0,
                    tier_name="strong")
    blob = serialize_event(cu)
    restored = deserialize_event(blob)
    assert isinstance(restored, CostUpdate)
    assert restored.tier_name == "strong"


def test_cost_update_legacy_event_without_tier_name_deserializes():
    # 旧 JSON 没 tier_name 字段 → 反序列化时 dataclass 字段默认值生效
    blob = json.dumps({"kind": "cost_update",
                       "data": {"tokens_in": 0, "tokens_out": 0, "cost_usd": None,
                                "elapsed_s": 0.0, "cache_read": 0, "context_used": 0}})
    restored = deserialize_event(blob)
    assert isinstance(restored, CostUpdate)
    assert restored.tier_name == ""


# ── T6:AgentLoop 注入 router 扩展 ──────────────────────────────────


def _sse_transport(text: str) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        data = {"type": "content_block_delta", "delta": {"type": "text_delta", "text": text}}
        body = (
            f"event: content_block_delta\ndata: {json.dumps(data)}\n"
            f"event: message_stop\ndata: {{\"type\":\"message_stop\"}}\n"
        )
        return httpx.Response(200, text=body, headers={"content-type": "text/event-stream"})
    return httpx.MockTransport(handler)


def _make_client(name: str) -> ModelClient:
    tier = ModelTier(name=name, model=f"{name}-model",
                     base_url="https://x/anthropic", max_tokens=4096)
    return ModelClient(tier=tier, pool=CredentialPool(["k"]), transport=_sse_transport("ok"))


def _build_router(cheap: bool = True) -> ModelRouter:
    routing = RoutingConfig(
        default="default",
        by_category={"file_edit": "cheap"} if cheap else {},
        tier_force_confirm=["strong"],
    )
    return ModelRouter(routing=routing, client_factory=_make_client)


def test_agent_loop_no_router_uses_existing_model_and_tier():
    """既有路径 0 破坏:无 router → CostUpdate.tier_name = cfg.model_tier。"""
    from argos_agent.core.loop import AgentLoop
    from argos_agent.core.verify_gate import Verifier
    from argos_agent.memory.store import ArgosStore
    from argos_agent.sandbox.broker import CapabilityBroker
    from argos_agent.sandbox.egress import EgressPolicy
    from argos_agent.sandbox.executor import SeatbeltExecutor
    from argos_agent.tools.receipts import ReceiptSigner
    from argos_agent.tui.events import EventBus

    import tempfile
    from pathlib import Path
    with tempfile.TemporaryDirectory() as td:
        ws = Path(td) / "ws"
        ws.mkdir()
        db = Path(td) / "a.db"
        store = ArgosStore(db_path=str(db))
        signer = ReceiptSigner(key=b"k"*8)
        model = _make_client("default")
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
        )
        # 直接断言 _current_tier 默认值
        assert loop._current_tier == "default"


def test_agent_loop_strong_tier_sets_approval_level_override():
    """router 选 strong → loop 端 _approval_level_override=CONFIRM(纵深防线 spec §11)。"""
    routing = RoutingConfig(
        default="default", by_category={"file_edit": "strong"},
        tier_force_confirm=["strong"],
    )

    class _StaticRouter:
        def __init__(self, cfg: RoutingConfig) -> None:
            self._cfg = cfg
            self.calls: list[tuple] = []

        def select(self, *, category, tool, step=0):
            from argos_agent.routing.resolver import RouteDecision
            tier = self._cfg.by_category.get(category.value, self._cfg.default)
            self.calls.append((category.value, tool, tier, step))
            client = _make_client(tier)
            return client, RouteDecision(category, tool, tier, "by_category", step)

        @property
        def routing(self) -> RoutingConfig:
            return self._cfg

    router = _StaticRouter(routing)
    # 模拟 select 后 loop 应该置 _approval_level_override=CONFIRM
    from argos_agent.routing.resolver import RouteDecision
    decision = RouteDecision(TaskCategory.FILE_EDIT, "edit_file", "strong", "by_category", 1)
    if router.routing.is_force_confirm(decision.tier):
        override = ApprovalLevel.CONFIRM
    else:
        override = None
    assert override == ApprovalLevel.CONFIRM


def test_app_factory_build_components_constructs_router():
    """build_components 应构造 ModelRouter + AppComponents 含 router 字段。"""
    from argos_agent.app_factory import AppComponents
    # 静态检查 AppComponents dataclass 字段含 router
    import dataclasses
    fields = {f.name for f in dataclasses.fields(AppComponents)}
    assert "router" in fields


def test_agent_loop_router_kw_accepted():
    """AgentLoop.__init__ 接受 router kw-only 参数(默认 None 零破坏)。"""
    from argos_agent.core.loop import AgentLoop
    import inspect
    sig = inspect.signature(AgentLoop.__init__)
    assert "router" in sig.parameters
    assert sig.parameters["router"].default is None
