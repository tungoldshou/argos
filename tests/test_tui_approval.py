"""Phase 5 审批:ApprovalGate 4 级 respond(契约 §6.3,canonical 接口)+ InlineChoice 流内审批
(TUI v2:1=once 2=session 3=always 4=deny,↑↓+Enter 与数字双通道,Esc=deny)。"""
from __future__ import annotations

import asyncio

import pytest
from textual.app import App, ComposeResult

from argos_agent.approval import ApprovalGate, ApprovalLevel, Decision
from argos_agent.tui.events import ApprovalRequest
from argos_agent.tui.theme import ARGOS_NIGHT
from argos_agent.tui.widgets.inline_choice import InlineChoice


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
        # timeout=30s:测的是审批放行语义,不测超时路径 —— 宽松避免 xdist 高负载下
        # 轮询耗尽 pending 窗口(原 5s)前 request 自己超时把 _pending 弹出。
        return await g.request(
            "run_command", {"command": "pytest"},
            description="执行命令 pytest", risk="medium", timeout=30.0,
        )

    task = asyncio.create_task(_caller())
    # 等 pending 出现。xdist 并行时 worker 可能有 CPU 争抢,用更大的轮询窗口(最多 20s)。
    # 关键:request timeout(30s) >> 轮询窗口(20s),保证 pending 项不在轮询期间超时被弹出。
    for _ in range(2000):   # 最多 20s(2000 × 10ms);正常 <50ms
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
    """挂一个工具审批 InlineChoice 的临时宿主(对位旧 _ModalHost)。

    注入 argos-night token:InlineChoice DEFAULT_CSS 引用 $raise/$unverif 等 v3 token,
    需在 CSS 解析前(即 get_theme_variable_defaults)注入才能解析。
    """

    def __init__(self, req: ApprovalRequest) -> None:
        super().__init__()
        self._req = req
        self.result: str | None = None

    def get_theme_variable_defaults(self) -> dict[str, str]:
        """把 ARGOS_NIGHT variables 作为 CSS token 兜底注入。"""
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
        await pilot.press("1")   # TUI v2:1 = once(安全向前走排第一)
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
    """Esc = 安全默认拒绝(fail-closed)。"""
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
    """↑↓ + Enter 通道:↓ 一次选中第 2 项(session)。"""
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
