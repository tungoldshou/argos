"""Internal documentation."""
from __future__ import annotations

import asyncio

import pytest
from textual.app import App, ComposeResult

from argos.approval import ApprovalGate, ApprovalLevel, Decision
from argos.tui.events import ApprovalRequest
from argos.tui.theme import ARGOS_NIGHT
from argos.tui.widgets.inline_choice import InlineChoice


def test_gate_level_default_and_set():
    g = ApprovalGate()
    assert g.level is ApprovalLevel.CONFIRM
    g.set_level(ApprovalLevel.AUTO)
    assert g.level is ApprovalLevel.AUTO


def test_decision_kinds():
    """Internal documentation."""
    assert Decision(kind="deny").approved is False
    assert Decision(kind="deny").kind == "deny"
    assert Decision(kind="once").approved is True
    assert Decision(kind="session").kind == "session"
    assert Decision(kind="always").approved is True


@pytest.mark.asyncio
async def test_gate_request_then_respond_session_resolves():
    g = ApprovalGate()

    async def _caller() -> Decision:
        return await g.request(
            "run_command", {"command": "pytest"},
            description="执行命令 pytest", risk="medium", timeout=30.0,
        )

    task = asyncio.create_task(_caller())
    for _ in range(2000):
        await asyncio.sleep(0.01)
        if g.pending():
            break
    pend = g.pending()
    assert len(pend) == 1
    call_id = pend[0].call_id
    assert g.respond(call_id, "session") is True
    dec = await asyncio.wait_for(task, timeout=5.0)
    assert dec.approved is True and dec.kind == "session"


_TOOL_OPTIONS = [
    ("once", "本次允许"), ("session", "本会话允许"),
    ("always", "总是允许"), ("deny", "拒绝"),
]


class _ChoiceHost(App):
    """Internal documentation."""

    def __init__(self, req: ApprovalRequest) -> None:
        super().__init__()
        self._req = req
        self.result: str | None = None

    def get_theme_variable_defaults(self) -> dict[str, str]:
        """Internal documentation."""
        defaults = super().get_theme_variable_defaults()
        if ARGOS_NIGHT.variables:
            defaults.update(ARGOS_NIGHT.variables)
        return defaults

    def compose(self) -> ComposeResult:
        yield InlineChoice(
            title=f"审批请求 [{self._req.risk}]",
            body=self._req.description,
            options=list(_TOOL_OPTIONS),
            on_decide=self._decide,
            escape_value="deny",
            risk=self._req.risk,
        )

    def _decide(self, value: str, _feedback: str) -> None:
        self.result = value


@pytest.mark.asyncio
async def test_choice_key_1_returns_once():
    req = ApprovalRequest(
        call_id="abc123", action="run_command",
        args={"command": "pytest -q"}, description="执行命令 pytest -q", risk="medium",
    )
    app = _ChoiceHost(req)
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("1")
        await pilot.pause()
        assert app.result == "once"


@pytest.mark.asyncio
async def test_choice_key_4_returns_deny():
    req = ApprovalRequest(
        call_id="abc123", action="git_push", args={}, description="git push", risk="high",
    )
    app = _ChoiceHost(req)
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("4")   # TUI v2:4 = deny
        await pilot.pause()
        assert app.result == "deny"


@pytest.mark.asyncio
async def test_choice_key_3_returns_always():
    req = ApprovalRequest(
        call_id="abc123", action="web_search", args={"query": "x"}, description="web_search x", risk="low",
    )
    app = _ChoiceHost(req)
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("3")   # TUI v2:3 = always
        await pilot.pause()
        assert app.result == "always"


@pytest.mark.asyncio
async def test_choice_escape_returns_deny():
    """Internal documentation."""
    req = ApprovalRequest(
        call_id="abc123", action="git_push", args={}, description="git push", risk="high",
    )
    app = _ChoiceHost(req)
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("escape")
        await pilot.pause()
        assert app.result == "deny"


@pytest.mark.asyncio
async def test_choice_arrow_down_enter_returns_session():
    """Internal documentation."""
    req = ApprovalRequest(
        call_id="abc123", action="run_command",
        args={"command": "ls"}, description="ls", risk="low",
    )
    app = _ChoiceHost(req)
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("down")
        await pilot.press("enter")
        await pilot.pause()
        assert app.result == "session"
