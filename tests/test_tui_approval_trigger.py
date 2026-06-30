"""审批标题 trigger 标签 + secret 副标题 铁证(spec §2.6, D6 锁;TUI v2 迁至 InlineChoice)。

格式化逻辑原样迁移到 inline_choice.format_approval_title(标签语义不变);
secret 副标题由 app._handle_approval 拼进 InlineChoice body(集成测试钉)。
"""
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
    assert "—" not in t  # 无 trigger 不附加标签


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
    # v3 spec §4.7:secret 命中格式 = "◓ 审批请求 [risk] · ⚠︎ 命中密钥模式 X"(非旧 v2 [secret: X] 标签)
    t = format_approval_title(risk="high", trigger="secret:AWS access key")
    assert "⚠︎" in t and "命中密钥模式" in t and "AWS access key" in t


def test_title_soft_allow_not_shown():
    """soft allow 命中不弹审批(直接过),无 trigger 时不强行加 [allow] 标签。"""
    t = format_approval_title(risk="low", trigger="")
    assert "allow" not in t


def test_title_unknown_prefix_no_tag():
    t = format_approval_title(risk="medium", trigger="whatever:x")
    assert t.endswith("[medium]")


@pytest.mark.asyncio
async def test_app_renders_inline_choice_with_secret_subtitle():
    """app._handle_approval:secret 命中 → InlineChoice body 含 did-you-mean 提示 + 标题含标签。"""
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
        # v3 spec §4.7:secret 命中标题格式 = "· ⚠︎ 命中密钥模式 X"(非旧 v2 [secret: X] 标签)
        assert "⚠︎" in title and "命中密钥模式" in title and "AWS access key" in title
        assert "did you mean to commit" in body
        # 清理:按 4 拒绝收掉(决策回 gate;respond 无 pending 返 False 不碍)
        await pilot.press("4")
        await pilot.pause()
