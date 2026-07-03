"""Internal documentation."""
from __future__ import annotations

import pytest

from argos.approval import ApprovalGate, ApprovalLevel
from argos.tui.app import ArgosApp
from argos.tui.events import ApprovalRequest
from argos.tui.fakeloop import FakeLoop
from argos.tui.widgets.inline_choice import InlineChoice, format_approval_title


def test_title_no_trigger():
    t = format_approval_title(risk="low", trigger="")
    assert "审批请求" in t and "[low]" in t
    assert "—" not in t


def test_title_hard_rule():
    t = format_approval_title(risk="high", trigger="hard_rule:rm_rf_root")
    assert "[hard rule: rm_rf_root]" in t


def test_title_soft_ask():
    t = format_approval_title(risk="high", trigger="soft_ask:^npm publish")
    assert "[soft rule: ask" in t


def test_title_level_confirm():
    t = format_approval_title(risk="medium", trigger="level:confirm")
    assert "[level: confirm]" in t


def test_title_secret():
    t = format_approval_title(risk="high", trigger="secret:AWS access key")
    assert "⚠︎" in t and "命中密钥模式" in t and "AWS access key" in t


def test_title_soft_allow_not_shown():
    """Internal documentation."""
    t = format_approval_title(risk="low", trigger="")
    assert "allow" not in t


def test_title_unknown_prefix_no_tag():
    t = format_approval_title(risk="medium", trigger="whatever:x")
    assert t.endswith("[medium]")


@pytest.mark.asyncio
async def test_app_renders_inline_choice_with_secret_subtitle():
    """Internal documentation."""
    app = ArgosApp(loop_factory=lambda **kw: FakeLoop(),
                   gate=ApprovalGate(ApprovalLevel.CONFIRM))
    req = ApprovalRequest(
        call_id="c1", action="write_file", args={"path": "a.py", "content": "AKIA..."},
        description="write_file a.py", risk="high",
        trigger="secret:AWS access key", secret_pattern="AWS access key",
    )
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        await app._handle_approval(req)
        await pilot.pause()
        choices = list(app.query(InlineChoice))
        assert len(choices) == 1, "审批应在流内渲染一个 InlineChoice"
        c = choices[0]
        title = str(c.query_one("#ic-title").render())
        body = str(c.query_one("#ic-body").render())
        assert "⚠︎" in title and "命中密钥模式" in title and "AWS access key" in title
        assert "did you mean to commit" in body
        await pilot.press("4")
        await pilot.pause()
