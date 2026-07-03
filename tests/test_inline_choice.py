from __future__ import annotations

import pytest
from textual.app import App, ComposeResult

from argos.approval import ApprovalGate, ApprovalLevel
from argos.tui.app import ArgosApp
from argos.tui.events import ApprovalRequest
from argos.tui.fakeloop import FakeLoop
from argos.tui.theme import ARGOS_NIGHT
from argos.tui.widgets.inline_choice import InlineChoice, format_approval_title

_PLAN_OPTIONS = [
    ("approve_start", "Approve and start"),
    ("approve_accept_edits", "Approve and accept edits"),
    ("keep_planning", "Keep planning"),
    ("refine", "Refine with feedback"),
]


class _Host(App):

    def __init__(self, **kw) -> None:
        super().__init__()
        self._kw = kw
        self.decisions: list[tuple[str, str]] = []

    def get_theme_variable_defaults(self) -> dict[str, str]:
        defaults = super().get_theme_variable_defaults()
        if ARGOS_NIGHT.variables:
            defaults.update(ARGOS_NIGHT.variables)
        return defaults

    def compose(self) -> ComposeResult:
        kw = dict(
            title="◓ 审批请求 · medium",
            body="# Plan\n...",
            options=list(_PLAN_OPTIONS),
            on_decide=lambda v, f: self.decisions.append((v, f)),
            escape_value=None,
            needs_input={"refine"},
        )
        kw.update(self._kw)
        yield InlineChoice(**kw)


@pytest.mark.asyncio
async def test_plan_options_render_and_digit_select():
    app = _Host()
    async with app.run_test() as pilot:
        await pilot.pause()
        c = app.query_one(InlineChoice)
        opts = str(c.query_one("#ic-options").render())
        for _, label in _PLAN_OPTIONS:
            assert label in opts
        await pilot.press("3")
        await pilot.pause()
        assert app.decisions == [("keep_planning", "")]


@pytest.mark.asyncio
async def test_arrow_navigation_wraps_and_enter_confirms():
    app = _Host()
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("up")
        await pilot.pause()
        c = app.query_one(InlineChoice)
        assert c._cursor == len(_PLAN_OPTIONS) - 1
        await pilot.press("down")
        await pilot.press("down")    # 1
        await pilot.press("enter")
        await pilot.pause()
        assert app.decisions == [("approve_accept_edits", "")]


@pytest.mark.asyncio
async def test_refine_expands_input_and_submits_feedback():
    app = _Host()
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("4")
        await pilot.pause()
        c = app.query_one(InlineChoice)
        assert app.decisions == []
        assert c.has_class("-input-mode")
        for ch in "abc":
            await pilot.press(ch)
        await pilot.press("enter")
        await pilot.pause()
        assert app.decisions == [("refine", "abc")]


@pytest.mark.asyncio
async def test_refine_input_escape_returns_to_options():
    app = _Host()
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("4")
        await pilot.pause()
        c = app.query_one(InlineChoice)
        assert c.has_class("-input-mode")
        await pilot.press("escape")
        await pilot.pause()
        assert not c.has_class("-input-mode")
        assert app.decisions == []
        await pilot.press("1")
        await pilot.pause()
        assert app.decisions == [("approve_start", "")]


@pytest.mark.asyncio
async def test_escape_ignored_without_escape_value():
    app = _Host()
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("escape")
        await pilot.pause()
        assert app.decisions == []
        assert app.query(InlineChoice)


@pytest.mark.asyncio
async def test_decision_is_idempotent_and_removes_widget():
    app = _Host()
    async with app.run_test() as pilot:
        await pilot.pause()
        c = app.query_one(InlineChoice)
        await pilot.press("1")
        await pilot.pause()
        assert not list(app.query(InlineChoice)), "决策后组件应自毁"
        c._finish("approve_start", "")
        assert app.decisions == [("approve_start", "")]


@pytest.mark.asyncio
async def test_bell_rings_on_mount(monkeypatch):
    rang: list[bool] = []
    app = _Host()
    monkeypatch.setattr(type(app), "bell", lambda self: rang.append(True))
    async with app.run_test() as pilot:
        await pilot.pause()
        assert rang, "InlineChoice mount 应触发终端铃"


@pytest.mark.asyncio
async def test_app_queue_serializes_two_approvals():
    gate = ApprovalGate(ApprovalLevel.CONFIRM)
    app = ArgosApp(loop_factory=lambda **kw: FakeLoop(), gate=gate)
    r1 = ApprovalRequest(call_id="c1", action="run_command", args={"command": "a"},
                         description="a", risk="low")
    r2 = ApprovalRequest(call_id="c2", action="run_command", args={"command": "b"},
                         description="b", risk="low")
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        await app._handle_approval(r1)
        await app._handle_approval(r2)
        await pilot.pause()
        assert len(list(app.query(InlineChoice))) == 1, "同屏最多一个活动 InlineChoice"
        await pilot.press("1")
        for _ in range(20):
            await pilot.pause()
            if len(list(app.query(InlineChoice))) == 1:
                break
        assert len(list(app.query(InlineChoice))) == 1, "r1 决策后 r2 应从队列 mount"
        await pilot.press("4")
        await pilot.pause()


@pytest.mark.asyncio
async def test_focus_returns_to_prompt_after_decision():
    gate = ApprovalGate(ApprovalLevel.CONFIRM)
    app = ArgosApp(loop_factory=lambda **kw: FakeLoop(), gate=gate)
    req = ApprovalRequest(call_id="c1", action="run_command", args={"command": "a"},
                          description="a", risk="low")
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        await app._handle_approval(req)
        await pilot.pause()
        c = app.query_one(InlineChoice)
        assert app.focused is c, "审批挂起时 InlineChoice 应夺焦"
        await pilot.press("1")
        await pilot.pause()
        assert app.focused is not None and app.focused.id == "prompt"



def test_format_approval_title_medium_has_eye_prefix():
    title = format_approval_title(risk="medium", trigger="soft_ask:git push")
    assert title.startswith("◓"), f"标题应以 ◓ 开头,实际: {title!r}"
    assert "medium" in title


def test_format_approval_title_high_risk():
    title = format_approval_title(risk="high", trigger="hard_rule:shell")
    assert title.startswith("◓"), f"标题应以 ◓ 开头,实际: {title!r}"
    assert "high" in title
    assert "hard rule" in title


def test_format_approval_title_low_risk():
    title = format_approval_title(risk="low", trigger="")
    assert title.startswith("◓"), f"标题应以 ◓ 开头,实际: {title!r}"
    assert "low" in title


def test_format_approval_title_secret_contains_warning():
    title = format_approval_title(risk="high", trigger="secret:AWS_KEY")
    assert "⚠︎" in title, f"secret trigger 应含 ⚠︎(VS15),实际: {title!r}"
    assert "AWS_KEY" in title


def test_format_approval_title_no_forbidden_glyphs():
    forbidden = set("◎⊙●○◐◑◇◆▶•")
    for risk in ("low", "medium", "high"):
        for trigger in ("", "hard_rule:x", "secret:K"):
            title = format_approval_title(risk=risk, trigger=trigger)
            for ch in forbidden:
                assert ch not in title, f"标题含被处决字形 {ch!r}: {title!r}"


@pytest.mark.asyncio
async def test_risk_classes_applied():
    for risk, expected_class in (("low", "risk-low"), ("medium", "risk-medium"), ("high", "risk-high")):
        app = _Host(risk=risk)
        async with app.run_test() as pilot:
            await pilot.pause()
            c = app.query_one(InlineChoice)
            assert c.has_class(expected_class), f"risk={risk} 时应有 CSS 类 {expected_class}"


@pytest.mark.asyncio
async def test_options_use_arrow_prefix():
    app = _Host()
    async with app.run_test() as pilot:
        await pilot.pause()
        c = app.query_one(InlineChoice)
        opts_text = str(c.query_one("#ic-options").render())
        assert "▸" in opts_text, "选中项应有 ▸ 前缀"


@pytest.mark.asyncio
async def test_self_destruct_line_has_done_eye(monkeypatch):
    done_texts: list[str] = []
    original_finish = InlineChoice._finish

    results: list[str] = []
    decisions: list[tuple[str, str]] = []

    app = _Host(
        title="◓ 审批请求 · medium",
        body="run_command · {cmd: ls}",
        options=[("once", "本次允许"), ("deny", "拒绝")],
        on_decide=lambda v, f: decisions.append((v, f)),
        escape_value="deny",
        action_label="run_command",
    )
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("1")   # once
        await pilot.pause()
        assert decisions == [("once", "")]
        statics = list(app.query("Static"))
        combined = " ".join(str(s.render()) for s in statics)
        assert "◕" in combined, f"决策后应存在含 ◕ 的摘要行,已渲染文本: {combined!r}"
