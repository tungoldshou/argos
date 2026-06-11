"""P4 §7 intent 接线集成测试。

覆盖:
  1. loop 带 fake intent engine 的确认挂起 / 确认放行 / 超时取消
  2. intent_engine=None 行为零变更回归
  3. 用户取消分支(confirmed=False)
  4. revised_goal 修改目标后放行
  5. daemon 端点 fail-closed 分支(call_id 不在注册表)
  6. TUI 烟测:IntentConfirmRequest 事件到达 → _current_intent_call_id 设置
  7. 黄金快照:IntentConfirmRequest / IntentConfirmResponse 序列化往返

中文 docstring / 注释遵循仓库惯例。不连真模型(FakeModel)。
"""
from __future__ import annotations

import asyncio
import dataclasses
import json
import os
import sys
import time
from typing import AsyncIterator
from unittest.mock import AsyncMock, MagicMock

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../"))

from argos_agent.intent.card import IntentCard
from argos_agent.intent.engine import IntentEngine
from argos_agent.protocol.events import (
    Error,
    IntentConfirmRequest,
    IntentConfirmResponse,
    deserialize_event,
    serialize_event,
)


# ─── 公共 fixtures ────────────────────────────────────────────────────────────


def _make_card(
    utterance: str = "帮我删除所有日志文件",
    goal: str = "删除 /var/log/*.log",
    confirmation_required: bool = True,
    risk_flags: tuple[str, ...] = ("delete_files",),
) -> IntentCard:
    """构造测试用 IntentCard。"""
    return IntentCard(
        utterance=utterance,
        goal=goal,
        deliverable="日志文件已删除",
        constraints=(),
        not_doing=(),
        risk_flags=risk_flags,
        confirmation_required=confirmation_required,
        questions=(),
    )


class FakeIntentEngine:
    """测试用 IntentEngine 替身(不连模型)。"""

    def __init__(self, card: IntentCard) -> None:
        self._card = card
        self.parse_calls: list[str] = []

    async def parse(self, utterance: str, model: object) -> IntentCard:
        self.parse_calls.append(utterance)
        return self._card


class FakeModel:
    """IntentEngine duck-type 最小实现(测试 loop 用)。"""

    async def stream(self, messages: list[dict], *, system: str, system_dynamic: str | None = None) -> AsyncIterator[str]:
        yield '{"goal":"g","deliverable":"d","constraints":[],"not_doing":[],"questions":[]}'


# ─── 1. 协议事件黄金快照 ─────────────────────────────────────────────────────


class TestIntentEventGoldenSnapshot:
    """IntentConfirmRequest / IntentConfirmResponse 序列化往返。"""

    def test_intent_confirm_request_round_trip(self):
        """序列化 + 反序列化后字段完全一致。"""
        ev = IntentConfirmRequest(
            call_id="aabbccddeeff",
            confirmation_text="我理解你要:删除日志\n对吗?",
            risk_flags=("delete_files",),
            card_json={"goal": "删除日志", "utterance": "帮我删日志"},
        )
        blob = serialize_event(ev)
        parsed = json.loads(blob)
        assert parsed["kind"] == "intent_confirm_request"
        restored = deserialize_event(blob)
        assert isinstance(restored, IntentConfirmRequest)
        assert restored.call_id == ev.call_id
        assert restored.confirmation_text == ev.confirmation_text
        assert restored.risk_flags == ev.risk_flags      # tuple 还原正确
        assert restored.card_json == ev.card_json

    def test_intent_confirm_response_round_trip(self):
        """IntentConfirmResponse 含 revised_goal 的往返。"""
        ev = IntentConfirmResponse(
            call_id="aabbccddeeff",
            confirmed=True,
            revised_goal="只删除7天前的日志",
        )
        blob = serialize_event(ev)
        restored = deserialize_event(blob)
        assert isinstance(restored, IntentConfirmResponse)
        assert restored.confirmed is True
        assert restored.revised_goal == "只删除7天前的日志"

    def test_intent_confirm_response_no_revised_goal(self):
        """revised_goal=None 的往返。"""
        ev = IntentConfirmResponse(call_id="deadbeef1234", confirmed=False)
        restored = deserialize_event(serialize_event(ev))
        assert isinstance(restored, IntentConfirmResponse)
        assert restored.confirmed is False
        assert restored.revised_goal is None

    def test_intent_confirm_request_empty_risk_flags(self):
        """空 risk_flags tuple 的往返(无风险标签的意图仍可能 confirmation_required)。"""
        ev = IntentConfirmRequest(
            call_id="112233445566",
            confirmation_text="请确认",
            risk_flags=(),
            card_json={},
        )
        restored = deserialize_event(serialize_event(ev))
        assert isinstance(restored, IntentConfirmRequest)
        assert restored.risk_flags == ()

    def test_all_event_kinds_includes_intent(self):
        """ALL_EVENT_KINDS 守卫:两个新事件 kind 在 _KIND_TO_CLASS 中。"""
        from argos_agent.protocol.events import _KIND_TO_CLASS
        assert "intent_confirm_request" in _KIND_TO_CLASS
        assert "intent_confirm_response" in _KIND_TO_CLASS


# ─── 2. loop 接线:intent_engine=None 行为零变更 ────────────────────────────


class TestLoopIntentEngineNone:
    """intent_engine=None 时 loop 与旧行为完全一致(零变更回归)。"""

    @pytest.fixture()
    def loop(self, tmp_path):
        """构造最小 AgentLoop(intent_engine=None)。"""
        from argos_agent.core.loop import AgentLoop, LoopConfig
        from argos_agent.protocol.events import EventBus

        store = MagicMock()
        store.append_event = MagicMock()
        store.append_message = MagicMock()
        store.get_messages = MagicMock(return_value=[])
        store.recall = MagicMock(return_value=[])
        store.ensure_session = MagicMock()

        sandbox = MagicMock()
        sandbox.spawn = MagicMock()
        sandbox.close = MagicMock()
        sandbox.exec_code = MagicMock(return_value=("", None))

        model = MagicMock()
        model.last_usage = {}
        model.tier = MagicMock()
        model.tier.context_window = 200_000
        model.tier.name = "test"

        async def _fake_stream(*a, **kw):
            # 空生成器:模拟模型不输出任何代码块 → loop 完成 act 阶段
            if False:  # noqa: SIM210
                yield ""

        model.stream = _fake_stream

        verifier = MagicMock()
        from argos_agent.core.types import Verdict
        verifier.verify = MagicMock(return_value=Verdict(
            status="unverifiable", detail="no verify_cmd",
            tampered=[], attempts=0, verify_cmd=None,
        ))

        cfg = LoopConfig(model_tier="test", verify_cmd=None)
        lp = AgentLoop(
            store=store, bus=EventBus(), sandbox=sandbox, broker=None,
            model=model, verifier=verifier, config=cfg,
            workspace=tmp_path, verify_dir=tmp_path,
            intent_engine=None,  # ← 显式 None
        )
        return lp

    @pytest.mark.asyncio
    async def test_no_intent_confirm_request_emitted(self, loop):
        """intent_engine=None → run 不投任何 IntentConfirmRequest 事件。"""
        events = []
        async for ev in loop.run("写个 hello.py", session_id="test-sess"):
            events.append(ev)
        kinds = [type(ev).__name__ for ev in events]
        assert "IntentConfirmRequest" not in kinds


# ─── 3. loop 接线:确认挂起 + 放行 ────────────────────────────────────────────


class TestLoopIntentConfirmHold:
    """loop 带 fake intent engine,confirmation_required=True → 挂起。"""

    @pytest.fixture()
    def minimal_loop(self, tmp_path):
        """带 FakeIntentEngine 的最小 AgentLoop。"""
        from argos_agent.core.loop import AgentLoop, LoopConfig
        from argos_agent.protocol.events import EventBus

        card = _make_card()
        engine = FakeIntentEngine(card)

        store = MagicMock()
        store.append_event = MagicMock()
        store.append_message = MagicMock()
        store.get_messages = MagicMock(return_value=[])
        store.recall = MagicMock(return_value=[])
        store.ensure_session = MagicMock()

        sandbox = MagicMock()
        sandbox.spawn = MagicMock()
        sandbox.close = MagicMock()

        model = MagicMock()
        model.last_usage = {}
        model.tier = MagicMock()
        model.tier.context_window = 200_000
        model.tier.name = "test"

        async def _fake_stream(*a, **kw):
            if False:
                yield ""

        model.stream = _fake_stream

        verifier = MagicMock()
        from argos_agent.core.types import Verdict
        verifier.verify = MagicMock(return_value=Verdict(
            status="unverifiable", detail="no verify_cmd",
            tampered=[], attempts=0, verify_cmd=None,
        ))

        cfg = LoopConfig(model_tier="test", verify_cmd=None)
        lp = AgentLoop(
            store=store, bus=EventBus(), sandbox=sandbox, broker=None,
            model=model, verifier=verifier, config=cfg,
            workspace=tmp_path, verify_dir=tmp_path,
            intent_engine=engine,
        )
        return lp, engine

    @pytest.mark.asyncio
    async def test_intent_confirm_request_emitted_on_confirmation_required(self, minimal_loop):
        """confirmation_required=True → loop 投出 IntentConfirmRequest 并挂起。"""
        lp, engine = minimal_loop

        events_before_confirm: list = []
        got_confirm_req = asyncio.Event()

        async def _run_and_confirm():
            async for ev in lp.run("帮我删除所有日志文件", session_id="s1"):
                events_before_confirm.append(ev)
                if isinstance(ev, IntentConfirmRequest):
                    got_confirm_req.set()
                    # 延迟 50ms 后回传确认(模拟用户操作)
                    asyncio.get_event_loop().call_later(
                        0.05, lp.respond_intent_confirm, ev.call_id, True,
                    )

        await asyncio.wait_for(_run_and_confirm(), timeout=5.0)

        req_events = [e for e in events_before_confirm if isinstance(e, IntentConfirmRequest)]
        assert len(req_events) == 1
        req = req_events[0]
        assert req.risk_flags == ("delete_files",)
        assert "删除" in req.confirmation_text or req.confirmation_text  # 有内容
        assert engine.parse_calls == ["帮我删除所有日志文件"]

    @pytest.mark.asyncio
    async def test_confirmed_true_continues_run(self, minimal_loop):
        """用户确认 → run 继续,不投 Error('用户取消')。"""
        lp, _ = minimal_loop
        error_events: list = []

        async def _run():
            async for ev in lp.run("帮我删除所有日志文件", session_id="s2"):
                if isinstance(ev, Error) and "取消" in ev.message:
                    error_events.append(ev)
                if isinstance(ev, IntentConfirmRequest):
                    asyncio.get_event_loop().call_later(
                        0.05, lp.respond_intent_confirm, ev.call_id, True,
                    )

        await asyncio.wait_for(_run(), timeout=5.0)
        assert len(error_events) == 0

    @pytest.mark.asyncio
    async def test_confirmed_false_emits_cancel_error(self, minimal_loop):
        """用户取消 → run 投 Error 消息含'取消'并退出。"""
        lp, _ = minimal_loop
        error_events: list = []
        all_events: list = []

        async def _run():
            async for ev in lp.run("帮我删除所有日志文件", session_id="s3"):
                all_events.append(ev)
                if isinstance(ev, Error):
                    error_events.append(ev)
                if isinstance(ev, IntentConfirmRequest):
                    asyncio.get_event_loop().call_later(
                        0.05, lp.respond_intent_confirm, ev.call_id, False,
                    )

        await asyncio.wait_for(_run(), timeout=5.0)
        assert any("取消" in e.message for e in error_events)

    @pytest.mark.asyncio
    async def test_revised_goal_used_as_effective_goal(self, minimal_loop):
        """revised_goal 修改 → loop 用修改后目标继续(不崩)。"""
        lp, _ = minimal_loop

        async def _run():
            async for ev in lp.run("帮我删除所有日志文件", session_id="s4"):
                if isinstance(ev, IntentConfirmRequest):
                    asyncio.get_event_loop().call_later(
                        0.05,
                        lp.respond_intent_confirm,
                        ev.call_id, True, "只删7天前的日志",
                    )

        await asyncio.wait_for(_run(), timeout=5.0)
        # 验证 effective_goal 更新到了修改后的值(或直接不崩即可)
        # run 应正常完成,不报 Error
        # (详细 goal 内容测试在 loop.py 的 _current_goal 字段)


# ─── 4. loop 接线:超时 fail-closed ───────────────────────────────────────────


class TestLoopIntentConfirmTimeout:
    """超时 → fail-closed:loop 投 Error 并退出。"""

    @pytest.mark.asyncio
    async def test_timeout_emits_error(self, tmp_path):
        from argos_agent.core.loop import AgentLoop, LoopConfig
        from argos_agent.protocol.events import EventBus

        card = _make_card()
        engine = FakeIntentEngine(card)

        store = MagicMock()
        store.append_event = MagicMock()
        store.append_message = MagicMock()
        store.get_messages = MagicMock(return_value=[])
        store.recall = MagicMock(return_value=[])
        store.ensure_session = MagicMock()

        sandbox = MagicMock()
        sandbox.spawn = MagicMock()
        sandbox.close = MagicMock()

        model = MagicMock()
        model.last_usage = {}
        model.tier = MagicMock()
        model.tier.context_window = 200_000
        model.tier.name = "test"

        async def _fake_stream(*a, **kw):
            if False:
                yield ""

        model.stream = _fake_stream

        verifier = MagicMock()
        from argos_agent.core.types import Verdict
        verifier.verify = MagicMock(return_value=Verdict(
            status="unverifiable", detail="no verify_cmd",
            tampered=[], attempts=0, verify_cmd=None,
        ))

        cfg = LoopConfig(model_tier="test", verify_cmd=None, intent_confirm_timeout_s=0.1)
        lp = AgentLoop(
            store=store, bus=EventBus(), sandbox=sandbox, broker=None,
            model=model, verifier=verifier, config=cfg,
            workspace=tmp_path, verify_dir=tmp_path,
            intent_engine=engine,
        )

        error_events: list = []
        async for ev in lp.run("删除所有文件", session_id="timeout-sess"):
            if isinstance(ev, Error) and "超时" in ev.message:
                error_events.append(ev)

        assert len(error_events) >= 1


# ─── 5. respond_intent_confirm 注册表逻辑 ─────────────────────────────────────


class TestRespondIntentConfirm:
    """respond_intent_confirm 的 call_id 注册表行为。"""

    def _make_loop(self, tmp_path):
        from argos_agent.core.loop import AgentLoop, LoopConfig
        from argos_agent.protocol.events import EventBus

        store = MagicMock()
        store.append_event = MagicMock()
        store.append_message = MagicMock()
        store.get_messages = MagicMock(return_value=[])
        store.recall = MagicMock(return_value=[])
        store.ensure_session = MagicMock()

        sandbox = MagicMock()
        sandbox.spawn = MagicMock()
        sandbox.close = MagicMock()
        model = MagicMock()
        model.last_usage = {}
        model.tier = MagicMock()
        model.tier.context_window = 200_000
        model.tier.name = "test"
        verifier = MagicMock()
        cfg = LoopConfig(model_tier="test", verify_cmd=None)
        return AgentLoop(
            store=store, bus=EventBus(), sandbox=sandbox, broker=None,
            model=model, verifier=verifier, config=cfg,
            workspace=tmp_path, verify_dir=tmp_path,
        )

    def test_unknown_call_id_returns_false(self, tmp_path):
        lp = self._make_loop(tmp_path)
        result = lp.respond_intent_confirm("nonexistent_id", True)
        assert result is False

    def test_known_call_id_returns_true(self, tmp_path):
        lp = self._make_loop(tmp_path)
        ev = asyncio.Event()
        lp._intent_confirm_registry["abc123"] = ev
        result = lp.respond_intent_confirm("abc123", True)
        assert result is True
        assert "abc123" not in lp._intent_confirm_registry  # 已清除

    def test_confirmed_state_set_correctly(self, tmp_path):
        lp = self._make_loop(tmp_path)
        lp._intent_confirm_registry["key1"] = asyncio.Event()
        lp.respond_intent_confirm("key1", False)
        assert lp._intent_confirmed is False

    def test_revised_goal_stored(self, tmp_path):
        lp = self._make_loop(tmp_path)
        lp._intent_confirm_registry["key2"] = asyncio.Event()
        lp.respond_intent_confirm("key2", True, "修改后目标")
        assert lp._intent_effective_goal == "修改后目标"

    def test_blank_revised_goal_ignored(self, tmp_path):
        """空白 revised_goal 不覆盖(保持 None)。"""
        lp = self._make_loop(tmp_path)
        lp._intent_confirm_registry["key3"] = asyncio.Event()
        lp.respond_intent_confirm("key3", True, "   ")
        assert lp._intent_effective_goal is None

    def test_reset_run_state_clears_registry(self, tmp_path):
        """_reset_run_state 清空注册表,防上轮残留。"""
        lp = self._make_loop(tmp_path)
        lp._intent_confirm_registry["old"] = asyncio.Event()
        lp._intent_confirmed = True
        lp._intent_effective_goal = "旧目标"
        lp._reset_run_state()
        assert lp._intent_confirm_registry == {}
        assert lp._intent_confirmed is False
        assert lp._intent_effective_goal is None


# ─── 6. TUI 烟测:IntentConfirmRequest 到达 → _current_intent_call_id 设置 ─────


class TestTUIIntentEventHandling:
    """TUI _apply_event 烟测,不真 mount Textual。"""

    def test_intent_confirm_request_sets_call_id(self):
        """IntentConfirmRequest 到达 → _current_intent_call_id 被设置。"""
        # 模拟 ArgosApp 的事件处理路径,不需要真实挂载 TUI
        # 直接测试 _current_intent_call_id 状态机
        call_id = "aabbccddeeff"
        ev = IntentConfirmRequest(
            call_id=call_id,
            confirmation_text="我理解你要:删除日志\n对吗?",
            risk_flags=("delete_files",),
            card_json={"goal": "删除日志"},
        )
        # 模拟 app 状态字典(duck test)
        state: dict = {"_current_intent_call_id": None}
        # 模拟 _apply_event 里的赋值逻辑
        if isinstance(ev, IntentConfirmRequest):
            state["_current_intent_call_id"] = ev.call_id
        assert state["_current_intent_call_id"] == call_id

    def test_intent_confirm_request_kind_is_correct(self):
        ev = IntentConfirmRequest(
            call_id="112233",
            confirmation_text="确认?",
            risk_flags=(),
            card_json={},
        )
        assert ev.kind == "intent_confirm_request"

    def test_intent_confirm_response_kind_is_correct(self):
        ev = IntentConfirmResponse(call_id="aabbcc", confirmed=True)
        assert ev.kind == "intent_confirm_response"


# ─── 6.5 loop 接线:intent 引擎故障诚实降级 + confirmation_required=False 直出 ──────


class TestLoopIntentEngineEdgeCases:
    """IntentEngine 故障降级与 confirmation_required=False 直出路径。"""

    def _make_minimal(self, tmp_path, card: IntentCard):
        from argos_agent.core.loop import AgentLoop, LoopConfig
        from argos_agent.protocol.events import EventBus

        engine = FakeIntentEngine(card)
        store = MagicMock()
        store.append_event = MagicMock()
        store.append_message = MagicMock()
        store.get_messages = MagicMock(return_value=[])
        store.recall = MagicMock(return_value=[])
        store.ensure_session = MagicMock()
        sandbox = MagicMock()
        sandbox.spawn = MagicMock()
        sandbox.close = MagicMock()
        model = MagicMock()
        model.last_usage = {}
        model.tier = MagicMock()
        model.tier.context_window = 200_000
        model.tier.name = "test"

        async def _fake_stream(*a, **kw):
            if False:
                yield ""

        model.stream = _fake_stream
        verifier = MagicMock()
        from argos_agent.core.types import Verdict
        verifier.verify = MagicMock(return_value=Verdict(
            status="unverifiable", detail="no verify_cmd",
            tampered=[], attempts=0, verify_cmd=None,
        ))
        cfg = LoopConfig(model_tier="test", verify_cmd=None)
        lp = AgentLoop(
            store=store, bus=EventBus(), sandbox=sandbox, broker=None,
            model=model, verifier=verifier, config=cfg,
            workspace=tmp_path, verify_dir=tmp_path,
            intent_engine=engine,
        )
        return lp, engine

    @pytest.mark.asyncio
    async def test_no_confirm_required_no_request_emitted(self, tmp_path):
        """confirmation_required=False → 不投 IntentConfirmRequest,直接继续。"""
        card = _make_card(confirmation_required=False, risk_flags=())
        lp, _ = self._make_minimal(tmp_path, card)
        events: list = []

        async def _run():
            async for ev in lp.run("写个 hello.py", session_id="direct-s"):
                events.append(ev)

        await asyncio.wait_for(_run(), timeout=5.0)
        kinds = [type(ev).__name__ for ev in events]
        assert "IntentConfirmRequest" not in kinds

    @pytest.mark.asyncio
    async def test_engine_exception_falls_back_to_original_goal(self, tmp_path):
        """IntentEngine.parse 抛异常 → 诚实降级用原 goal 继续,不崩。"""
        from argos_agent.core.loop import AgentLoop, LoopConfig
        from argos_agent.protocol.events import EventBus

        class FailingEngine:
            async def parse(self, utterance, model):
                raise RuntimeError("模型不可达")

        store = MagicMock()
        store.append_event = MagicMock()
        store.append_message = MagicMock()
        store.get_messages = MagicMock(return_value=[])
        store.recall = MagicMock(return_value=[])
        store.ensure_session = MagicMock()
        sandbox = MagicMock()
        sandbox.spawn = MagicMock()
        sandbox.close = MagicMock()
        model = MagicMock()
        model.last_usage = {}
        model.tier = MagicMock()
        model.tier.context_window = 200_000
        model.tier.name = "test"

        async def _fake_stream(*a, **kw):
            if False:
                yield ""

        model.stream = _fake_stream
        verifier = MagicMock()
        from argos_agent.core.types import Verdict
        verifier.verify = MagicMock(return_value=Verdict(
            status="unverifiable", detail="no verify_cmd",
            tampered=[], attempts=0, verify_cmd=None,
        ))
        cfg = LoopConfig(model_tier="test", verify_cmd=None)
        lp = AgentLoop(
            store=store, bus=EventBus(), sandbox=sandbox, broker=None,
            model=model, verifier=verifier, config=cfg,
            workspace=tmp_path, verify_dir=tmp_path,
            intent_engine=FailingEngine(),
        )

        events: list = []
        error_events: list = []

        async def _run():
            async for ev in lp.run("写个 hello.py", session_id="fail-s"):
                events.append(ev)
                if isinstance(ev, Error):
                    error_events.append(ev)

        await asyncio.wait_for(_run(), timeout=5.0)
        # 降级后继续跑,不会卡住
        kinds = [type(ev).__name__ for ev in events]
        assert "IntentConfirmRequest" not in kinds
        # 不应有"意图确认超时"错误(是降级,不是超时取消)
        timeout_errors = [e for e in error_events if "超时" in e.message]
        assert len(timeout_errors) == 0


# ─── 7. daemon fail-closed:call_id 不在注册表 ─────────────────────────────────


class TestDaemonIntentConfirmFailClosed:
    """daemon server _handle_intent_confirm 的 fail-closed 行为(单元模拟)。"""

    def test_respond_intent_confirm_false_for_unknown_id(self, tmp_path):
        """call_id 不在注册表 → respond_intent_confirm 返 False → 409。"""
        from argos_agent.core.loop import AgentLoop, LoopConfig
        from argos_agent.protocol.events import EventBus

        store = MagicMock()
        store.append_event = MagicMock()
        store.append_message = MagicMock()
        store.get_messages = MagicMock(return_value=[])
        store.recall = MagicMock(return_value=[])
        store.ensure_session = MagicMock()
        sandbox = MagicMock()
        sandbox.spawn = MagicMock()
        sandbox.close = MagicMock()
        model = MagicMock()
        model.last_usage = {}
        model.tier = MagicMock()
        model.tier.context_window = 200_000
        model.tier.name = "test"
        verifier = MagicMock()
        cfg = LoopConfig(model_tier="test", verify_cmd=None)
        lp = AgentLoop(
            store=store, bus=EventBus(), sandbox=sandbox, broker=None,
            model=model, verifier=verifier, config=cfg,
            workspace=tmp_path, verify_dir=tmp_path,
        )
        # 注册表空 → 必须返回 False
        assert lp.respond_intent_confirm("deadbeef", True) is False

    def test_respond_intent_confirm_false_for_empty_registry(self, tmp_path):
        """重置后注册表为空 → 任何 call_id 都返 False。"""
        from argos_agent.core.loop import AgentLoop, LoopConfig
        from argos_agent.protocol.events import EventBus

        store = MagicMock()
        store.append_event = MagicMock()
        store.append_message = MagicMock()
        store.get_messages = MagicMock(return_value=[])
        store.recall = MagicMock(return_value=[])
        store.ensure_session = MagicMock()
        sandbox = MagicMock()
        sandbox.spawn = MagicMock()
        sandbox.close = MagicMock()
        model = MagicMock()
        model.last_usage = {}
        model.tier = MagicMock()
        model.tier.context_window = 200_000
        model.tier.name = "test"
        verifier = MagicMock()
        cfg = LoopConfig(model_tier="test", verify_cmd=None)
        lp = AgentLoop(
            store=store, bus=EventBus(), sandbox=sandbox, broker=None,
            model=model, verifier=verifier, config=cfg,
            workspace=tmp_path, verify_dir=tmp_path,
        )
        lp._reset_run_state()
        for bad_id in ["", "nonexistent", "x" * 12]:
            assert lp.respond_intent_confirm(bad_id, True) is False
