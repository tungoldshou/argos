"""loop.py 多模态门禁 + 首条 user 消息挂 attachments 边车字段 TDD 验收(spec §5)。

仅测试 loop 新增行为：
  - 纯文本 tier + 附件 → HonestError(诚实阻断,不发请求)
  - multimodal tier + 附件 → run() 签名接受 attachments 参数
  - 无附件 run() → 行为与改造前一致(零回归)

使用最小化 mock，不依赖真实 sandbox / store / model。
"""
from __future__ import annotations

import asyncio
from typing import AsyncIterator
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ── 基础设施 ───────────────────────────────────────────────────────────────────

def _att(data: bytes = b"\x89PNG\x00", media_type: str = "image/png",
          source_label: str = "test.png"):
    from argos.input.attachments import ImageAttachment
    return ImageAttachment(data=data, media_type=media_type, source_label=source_label)


def _plain_tier():
    """纯文本模型(multimodal=False)。"""
    from argos.core.models import ModelTier
    return ModelTier(name="default", model="text-model", base_url="https://x",
                     max_tokens=64, multimodal=False)


def _mm_tier():
    """多模态模型(multimodal=True)。"""
    from argos.core.models import ModelTier
    return ModelTier(name="default", model="vision-model", base_url="https://x",
                     max_tokens=64, multimodal=True)


def _make_minimal_loop(tier):
    """构造最小化 AgentLoop，绑定给定 tier，其余组件全部 mock。"""
    from argos.core.loop import AgentLoop, LoopConfig
    from argos.approval import ApprovalLevel

    cfg = LoopConfig(
        model_tier="default",
        max_steps=1,
        approval_level=ApprovalLevel.AUTO,
    )
    loop = AgentLoop.__new__(AgentLoop)
    # 注入最小 mock 字段（loop 初始化依赖的字段）
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


# ── 多模态门禁 ────────────────────────────────────────────────────────────────

def test_run_signature_accepts_attachments():
    """AgentLoop.run() 签名接受可选 attachments 参数(不传 = None = 零回归)。"""
    from argos.core.loop import AgentLoop
    import inspect
    sig = inspect.signature(AgentLoop.run)
    assert "attachments" in sig.parameters


def test_run_attachments_default_is_none():
    """attachments 参数默认值为 None(零回归:既有调用不传也能工作)。"""
    from argos.core.loop import AgentLoop
    import inspect
    sig = inspect.signature(AgentLoop.run)
    param = sig.parameters["attachments"]
    assert param.default is None


@pytest.mark.asyncio
async def test_plain_tier_with_attachments_raises_honest_error():
    """纯文本 tier + attachments → 在 run 入口抛出诚实 ValueError,不发模型请求。

    诚实不变量(spec §5):绝不静默剥图、绝不假装看到。
    """
    from argos.core.loop import AgentLoop
    att = _att()

    # 最简 loop，仅测门禁是否触发
    loop = _make_minimal_loop(_plain_tier())

    events = []
    try:
        async for ev in loop.run("do something", "sess-1", attachments=[att]):
            events.append(ev)
    except Exception as e:
        # 如果门禁以异常形式出现也可接受
        assert "多模态" in str(e) or "multimodal" in str(e).lower() or "不支持" in str(e)
        return

    # 或者以 Error 事件形式发出
    from argos.protocol.events import Error
    error_events = [e for e in events if isinstance(e, Error)]
    assert error_events, "纯文本 tier 带附件应产生诚实阻断 Error 事件"
    msg = error_events[0].message
    assert "多模态" in msg or "multimodal" in msg.lower() or "不支持" in msg


@pytest.mark.asyncio
async def test_no_attachments_run_accepts_without_error():
    """无附件 run() → 不触发多模态门禁(零回归)。

    loop 后续可能因为 mock 不完整而出其他错误；此测试只保证门禁不会错误触发。
    """
    from argos.core.loop import AgentLoop
    loop = _make_minimal_loop(_plain_tier())

    events = []
    try:
        async for ev in loop.run("do something", "sess-2"):
            events.append(ev)
    except Exception as e:
        # 门禁异常必须包含 multimodal 相关词；其他错误(mock 不完整)允许
        assert "多模态" not in str(e) and "multimodal" not in str(e).lower(), (
            f"无附件时不应触发多模态门禁，但得到: {e}"
        )
