"""Phase 5 审批:ApprovalGate 4 级 respond(契约 §6.3,canonical 接口)+ ApprovalModal 键盘 1-4。"""
from __future__ import annotations

import asyncio

import pytest
from textual.app import App

from argos_agent.approval import ApprovalGate, ApprovalLevel, Decision
from argos_agent.tui.events import ApprovalRequest
from argos_agent.tui.widgets.approval_modal import ApprovalModal


def test_gate_level_default_and_set():
    g = ApprovalGate()
    assert g.level is ApprovalLevel.CONFIRM
    g.set_level(ApprovalLevel.AUTO)
    assert g.level is ApprovalLevel.AUTO


def test_decision_kinds():
    """canonical Decision:kind 字段 + approved property,无 scope。"""
    assert Decision(kind="deny").approved is False
    assert Decision(kind="deny").kind == "deny"
    assert Decision(kind="once").approved is True
    assert Decision(kind="session").kind == "session"
    assert Decision(kind="always").approved is True


@pytest.mark.asyncio
async def test_gate_request_then_respond_session_resolves():
    g = ApprovalGate()  # 默认 CONFIRM,会挂起等 respond

    async def _caller() -> Decision:
        return await g.request(
            "run_command", {"command": "pytest"},
            description="执行命令 pytest", risk="medium", timeout=5.0,
        )

    task = asyncio.create_task(_caller())
    # 等 pending 出现
    for _ in range(100):
        await asyncio.sleep(0.01)
        if g.pending():
            break
    pend = g.pending()
    assert len(pend) == 1
    call_id = pend[0].call_id
    assert g.respond(call_id, "session") is True
    dec = await asyncio.wait_for(task, timeout=2.0)
    assert dec.approved is True and dec.kind == "session"


class _ModalHost(App):
    def __init__(self) -> None:
        super().__init__()
        self.result: str | None = None

    async def open(self, req: ApprovalRequest) -> None:
        def _cb(decision: str | None) -> None:
            self.result = decision
        await self.push_screen(ApprovalModal(req), _cb)


@pytest.mark.asyncio
async def test_modal_key_2_returns_once():
    req = ApprovalRequest(
        call_id="abc123", action="run_command",
        args={"command": "pytest -q"}, description="执行命令 pytest -q", risk="medium",
    )
    app = _ModalHost()
    async with app.run_test() as pilot:
        await app.open(req)
        await pilot.pause()
        await pilot.press("2")   # 2 = once
        await pilot.pause()
        assert app.result == "once"


@pytest.mark.asyncio
async def test_modal_key_1_returns_deny():
    req = ApprovalRequest(
        call_id="abc123", action="git_push", args={}, description="git push", risk="high",
    )
    app = _ModalHost()
    async with app.run_test() as pilot:
        await app.open(req)
        await pilot.pause()
        await pilot.press("1")   # 1 = deny
        await pilot.pause()
        assert app.result == "deny"


@pytest.mark.asyncio
async def test_modal_key_4_returns_always():
    req = ApprovalRequest(
        call_id="abc123", action="web_search", args={"query": "x"}, description="web_search x", risk="low",
    )
    app = _ModalHost()
    async with app.run_test() as pilot:
        await app.open(req)
        await pilot.pause()
        await pilot.press("4")   # 4 = always
        await pilot.pause()
        assert app.result == "always"
