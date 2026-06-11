"""InlineChoice 流内选择组件(TUI v2/v3 spec §4.7)单元 + plan 决策 4 选项 + FIFO 队列。

取代旧 PlanModal/ApprovalModal/WorkflowApprovalModal 测试中的交互面:
↑↓+Enter / 数字直选 / Esc / refine 就地反馈输入 / 到达铃声 / 决策幂等 / app 队列。

v3 视觉断言更新:
  - 标题前缀 ◓(半阖眼,等用户决策)
  - 自毁结果行前缀 ◕(阅毕眼)
  - ⚠︎(U+26A0+U+FE0E) secret 副标
  - risk-high 用 $fail 左缘与标题色
"""
from __future__ import annotations

import pytest
from textual.app import App, ComposeResult

from argos_agent.approval import ApprovalGate, ApprovalLevel
from argos_agent.tui.app import ArgosApp
from argos_agent.tui.events import ApprovalRequest
from argos_agent.tui.fakeloop import FakeLoop
from argos_agent.tui.theme import ARGOS_NIGHT
from argos_agent.tui.widgets.inline_choice import InlineChoice, format_approval_title

_PLAN_OPTIONS = [
    ("approve_start", "Approve and start"),
    ("approve_accept_edits", "Approve and accept edits"),
    ("keep_planning", "Keep planning"),
    ("refine", "Refine with feedback"),
]


class _Host(App):
    """最小测试宿主:注入 argos-night token 以便 DEFAULT_CSS 中 $token 名在 CSS 解析阶段可用。

    override get_theme_variable_defaults() 是在 CSS 解析前就让 $token 可用的唯一手段——
    register_theme + self.theme 发生在 on_mount,晚于 DEFAULT_CSS 首次解析。
    """

    def __init__(self, **kw) -> None:
        super().__init__()
        self._kw = kw
        self.decisions: list[tuple[str, str]] = []

    def get_theme_variable_defaults(self) -> dict[str, str]:
        """把 ARGOS_NIGHT variables 作为 CSS token 兜底注入。"""
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
        await pilot.press("up")      # 从 0 上卷到最后一项之前先验证回绕
        await pilot.pause()
        c = app.query_one(InlineChoice)
        assert c._cursor == len(_PLAN_OPTIONS) - 1  # 回绕到末项(refine)
        await pilot.press("down")    # 回到 0
        await pilot.press("down")    # 1
        await pilot.press("enter")
        await pilot.pause()
        assert app.decisions == [("approve_accept_edits", "")]


@pytest.mark.asyncio
async def test_refine_expands_input_and_submits_feedback():
    """选 refine → 就地展开反馈输入 → Enter 提交带 feedback(不再返空串假反馈)。"""
    app = _Host()
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("4")       # refine(needs_input)→ 不立即决策
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
        await pilot.press("1")       # 回选项后仍可正常决策
        await pilot.pause()
        assert app.decisions == [("approve_start", "")]


@pytest.mark.asyncio
async def test_escape_ignored_without_escape_value():
    """plan 决策无"安全默认":Esc 不产生决策(用户没拍就让 loop 继续挂,诚实)。"""
    app = _Host()
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("escape")
        await pilot.pause()
        assert app.decisions == []
        assert app.query(InlineChoice)   # 组件仍在


@pytest.mark.asyncio
async def test_decision_is_idempotent_and_removes_widget():
    app = _Host()
    async with app.run_test() as pilot:
        await pilot.pause()
        c = app.query_one(InlineChoice)
        await pilot.press("1")
        await pilot.pause()
        assert not list(app.query(InlineChoice)), "决策后组件应自毁"
        c._finish("approve_start", "")   # 直接二次触发 → 幂等不双发
        assert app.decisions == [("approve_start", "")]


@pytest.mark.asyncio
async def test_bell_rings_on_mount(monkeypatch):
    """到达提示音:mount 时调 app.bell()(用户明确要求的音效)。"""
    rang: list[bool] = []
    app = _Host()
    monkeypatch.setattr(type(app), "bell", lambda self: rang.append(True))
    async with app.run_test() as pilot:
        await pilot.pause()
        assert rang, "InlineChoice mount 应触发终端铃"


@pytest.mark.asyncio
async def test_app_queue_serializes_two_approvals():
    """app FIFO:两个 ApprovalRequest 并发到达 → 同屏只渲染一个;前一个决策后第二个才出现。"""
    gate = ApprovalGate(ApprovalLevel.CONFIRM)
    app = ArgosApp(loop_factory=lambda: FakeLoop(), gate=gate)
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
        await pilot.press("1")        # 决 r1
        for _ in range(20):
            await pilot.pause()
            if len(list(app.query(InlineChoice))) == 1:
                break
        assert len(list(app.query(InlineChoice))) == 1, "r1 决策后 r2 应从队列 mount"
        await pilot.press("4")        # 决 r2(deny)收尾
        await pilot.pause()


@pytest.mark.asyncio
async def test_focus_returns_to_prompt_after_decision():
    """决策后焦点还给 #prompt(输入草稿不丢)。"""
    gate = ApprovalGate(ApprovalLevel.CONFIRM)
    app = ArgosApp(loop_factory=lambda: FakeLoop(), gate=gate)
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


# ── v3 视觉断言 ──────────────────────────────────────────────────────────────

def test_format_approval_title_medium_has_eye_prefix():
    """format_approval_title 标题前缀必须是 ◓(半阖眼,等用户决策)。"""
    title = format_approval_title(risk="medium", trigger="soft_ask:git push")
    assert title.startswith("◓"), f"标题应以 ◓ 开头,实际: {title!r}"
    assert "medium" in title


def test_format_approval_title_high_risk():
    """high 风险标题前缀 ◓,含 high 标签。"""
    title = format_approval_title(risk="high", trigger="hard_rule:shell")
    assert title.startswith("◓"), f"标题应以 ◓ 开头,实际: {title!r}"
    assert "high" in title
    assert "hard rule" in title


def test_format_approval_title_low_risk():
    """low 风险标题前缀 ◓。"""
    title = format_approval_title(risk="low", trigger="")
    assert title.startswith("◓"), f"标题应以 ◓ 开头,实际: {title!r}"
    assert "low" in title


def test_format_approval_title_secret_contains_warning():
    """secret trigger → 标题含 ⚠︎(U+26A0+U+FE0E) + 密钥名称。"""
    title = format_approval_title(risk="high", trigger="secret:AWS_KEY")
    # ⚠︎ = U+26A0 + U+FE0E (variation selector 15, 强制文本字形)
    assert "⚠︎" in title, f"secret trigger 应含 ⚠︎(VS15),实际: {title!r}"
    assert "AWS_KEY" in title


def test_format_approval_title_no_forbidden_glyphs():
    """标题中不得含被处决字形:◎⊙●○◐◑◇◆▶• 以及裸 ⚠(无 VS15)。"""
    forbidden = set("◎⊙●○◐◑◇◆▶•")
    for risk in ("low", "medium", "high"):
        for trigger in ("", "hard_rule:x", "secret:K"):
            title = format_approval_title(risk=risk, trigger=trigger)
            for ch in forbidden:
                assert ch not in title, f"标题含被处决字形 {ch!r}: {title!r}"


@pytest.mark.asyncio
async def test_risk_classes_applied():
    """risk 参数 → 正确的 CSS 类(risk-low / risk-medium / risk-high)。"""
    for risk, expected_class in (("low", "risk-low"), ("medium", "risk-medium"), ("high", "risk-high")):
        app = _Host(risk=risk)
        async with app.run_test() as pilot:
            await pilot.pause()
            c = app.query_one(InlineChoice)
            assert c.has_class(expected_class), f"risk={risk} 时应有 CSS 类 {expected_class}"


@pytest.mark.asyncio
async def test_options_use_arrow_prefix():
    """选项行当前项前缀为 ▸(U+25B8),非选中项为两空格缩进。"""
    app = _Host()
    async with app.run_test() as pilot:
        await pilot.pause()
        c = app.query_one(InlineChoice)
        opts_text = str(c.query_one("#ic-options").render())
        # 当前项(首项)有 ▸ 前缀
        assert "▸" in opts_text, "选中项应有 ▸ 前缀"


@pytest.mark.asyncio
async def test_self_destruct_line_has_done_eye(monkeypatch):
    """决策后自毁为一行,该行含 ◕(阅毕眼)。"""
    done_texts: list[str] = []
    # 拦截 remove(),改为记录自毁行文本
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
        # 决策后 InlineChoice 应已被 Summary Static 替换(或 remove)
        assert decisions == [("once", "")]
        # 查找 ◕ 结果行:自毁后挂一个 Static 到父容器
        # 检查父容器内 Static 文本含 ◕
        statics = list(app.query("Static"))
        combined = " ".join(str(s.render()) for s in statics)
        assert "◕" in combined, f"决策后应存在含 ◕ 的摘要行,已渲染文本: {combined!r}"
