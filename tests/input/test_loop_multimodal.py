from __future__ import annotations

import asyncio
from typing import AsyncIterator
from unittest.mock import AsyncMock, MagicMock, patch

import pytest



def _att(data: bytes = b"\x89PNG\x00", media_type: str = "image/png",
          source_label: str = "test.png"):
    from argos.input.attachments import ImageAttachment
    return ImageAttachment(data=data, media_type=media_type, source_label=source_label)


def _plain_tier():
    from argos.core.models import ModelTier
    return ModelTier(name="default", model="text-model", base_url="https://x",
                     max_tokens=64, multimodal=False)


def _mm_tier():
    from argos.core.models import ModelTier
    return ModelTier(name="default", model="vision-model", base_url="https://x",
                     max_tokens=64, multimodal=True)


def _make_minimal_loop(tier):
    from argos.core.loop import AgentLoop, LoopConfig
    from argos.approval import ApprovalLevel

    cfg = LoopConfig(
        model_tier="default",
        max_steps=1,
        approval_level=ApprovalLevel.AUTO,
    )
    loop = AgentLoop.__new__(AgentLoop)
    loop._cfg = cfg
    loop._model = MagicMock()
    loop._model.tier = tier
    loop._store = MagicMock()
    loop._store.get_messages = MagicMock(return_value=[])
    loop._store.append_message = MagicMock()
    loop._store.append_event = MagicMock()
    loop._workspace = MagicMock()
    loop._sandbox = MagicMock()
    loop._harness = MagicMock()
    loop._hbus = MagicMock()
    loop._hbus.drain = MagicMock(return_value=[])
    loop.mode = "act"
    loop._allow_workflow = False
    loop._read_only = False
    loop._last_snapshot = None
    loop._current_goal = ""
    loop._user_goal = ""
    loop._actions = []
    loop._approval_gate = MagicMock()
    return loop



def test_run_signature_accepts_attachments():
    from argos.core.loop import AgentLoop
    import inspect
    sig = inspect.signature(AgentLoop.run)
    assert "attachments" in sig.parameters


def test_run_attachments_default_is_none():
    from argos.core.loop import AgentLoop
    import inspect
    sig = inspect.signature(AgentLoop.run)
    param = sig.parameters["attachments"]
    assert param.default is None


@pytest.mark.asyncio
async def test_plain_tier_with_attachments_raises_honest_error():
    from argos.core.loop import AgentLoop
    att = _att()

    loop = _make_minimal_loop(_plain_tier())

    events = []
    try:
        async for ev in loop.run("do something", "sess-1", attachments=[att]):
            events.append(ev)
    except Exception as e:
        assert "多模态" in str(e) or "multimodal" in str(e).lower() or "不支持" in str(e)
        return

    from argos.protocol.events import Error
    error_events = [e for e in events if isinstance(e, Error)]
    assert error_events, "纯文本 tier 带附件应产生诚实阻断 Error 事件"
    msg = error_events[0].message
    assert "多模态" in msg or "multimodal" in msg.lower() or "不支持" in msg


@pytest.mark.asyncio
async def test_no_attachments_run_accepts_without_error():
    from argos.core.loop import AgentLoop
    loop = _make_minimal_loop(_plain_tier())

    events = []
    try:
        async for ev in loop.run("do something", "sess-2"):
            events.append(ev)
    except Exception as e:
        assert "多模态" not in str(e) and "multimodal" not in str(e).lower(), (
            f"无附件时不应触发多模态门禁，但得到: {e}"
        )


def _unknown_tier():
    from argos.core.models import ModelTier
    return ModelTier(name="default", model="agnes-flash", base_url="https://x",
                     max_tokens=64, multimodal=None)


@pytest.mark.asyncio
async def test_unknown_tier_blocks_when_resolve_false(monkeypatch):
    import argos.core.vision_capability as vc

    async def _fake_resolve(tier, model_client, cache, **kw):
        return False
    monkeypatch.setattr(vc, "resolve_vision_capability", _fake_resolve)

    loop = _make_minimal_loop(_unknown_tier())
    events = []
    try:
        async for ev in loop.run("x", "s", attachments=[_att()]):
            events.append(ev)
    except Exception as e:  # noqa: BLE001
        assert "看不了图" in str(e) or "multimodal" in str(e).lower()
        return
    from argos.protocol.events import Error
    assert any(isinstance(ev, Error) for ev in events), "resolve→False 应诚实阻断"


@pytest.mark.asyncio
async def test_unknown_tier_passes_gate_when_resolve_true(monkeypatch):
    import argos.core.vision_capability as vc

    async def _fake_resolve(tier, model_client, cache, **kw):
        return True
    monkeypatch.setattr(vc, "resolve_vision_capability", _fake_resolve)

    loop = _make_minimal_loop(_unknown_tier())
    try:
        async for _ev in loop.run("x", "s", attachments=[_att()]):
            pass
    except Exception as e:  # noqa: BLE001
        assert "看不了图" not in str(e) and "multimodal" not in str(e).lower(), (
            f"resolve→True 不应触发视觉门,但得到: {e}"
        )
