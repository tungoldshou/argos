"""Phase 5 端到端接线:FakeLoop 投全套 Event → 各 widget 出现/更新(Pilot)。
覆盖契约不变量:UI 看到的 = 事件源(一份事件三用的 UI 出口)。"""
from __future__ import annotations

import pytest

from argos_agent.approval import ApprovalLevel
from argos_agent.tui.app import ArgosApp
from argos_agent.tui.events import PhaseChange, TokenDelta
from argos_agent.tui.fakeloop import FakeLoop, FailingFakeLoop
from argos_agent.tui.widgets.code_action import CodeActionBlock
from argos_agent.tui.widgets.diff_view import DiffView
from argos_agent.tui.widgets.status_bar import StatusBar
from argos_agent.tui.widgets.verdict_badge import VerdictBadge


class _RaisingLoop:
    """yield 一个事件后抛异常 —— 验证 _produce 把异常降级成 Error 事件而非击穿 TUI(final review HIGH)。"""

    async def run(self, goal, session_id):
        yield PhaseChange(phase="act", actions=1)
        yield TokenDelta(text="干活中...\n")
        raise RuntimeError("模型 502 / sandbox 崩了")


@pytest.mark.asyncio
async def test_app_boots_with_status_bar_and_transcript():
    app = ArgosApp(loop_factory=lambda: FakeLoop())
    async with app.run_test() as pilot:
        await pilot.pause()
        assert app.query_one("#transcript") is not None
        assert app.query_one("#status-bar", StatusBar) is not None
        assert "Argos" in app.title


@pytest.mark.asyncio
async def test_run_goal_drives_widgets_from_events():
    app = ArgosApp(loop_factory=lambda: FakeLoop())
    async with app.run_test() as pilot:
        await pilot.pause()
        await app.start_run("修个 bug")
        await app.workers.wait_for_complete()
        await pilot.pause()
        blocks = list(app.query(CodeActionBlock))
        assert len(blocks) >= 1
        assert blocks[0].ok is True
        diffs = list(app.query(DiffView))
        assert any(d.path == "a.py" and d.added == 2 for d in diffs)
        badge = app.query_one(VerdictBadge)
        assert badge.status == "passed"
        bar = app.query_one("#status-bar", StatusBar)
        assert bar.phase == "report"
        assert "$0.013" in bar.render_text
        assert "12.4k" in bar.render_text


@pytest.mark.asyncio
async def test_failing_run_shows_escalation_and_failed_verdict():
    app = ArgosApp(loop_factory=lambda: FailingFakeLoop())
    async with app.run_test() as pilot:
        await pilot.pause()
        await app.start_run("会失败的任务")
        await app.workers.wait_for_complete()
        await pilot.pause()
        badge = app.query_one(VerdictBadge)
        assert badge.status == "failed"
        log = app.query_one("#transcript")
        assert "无法自行收敛" in log.rendered_text or "诚实上报" in log.rendered_text


@pytest.mark.asyncio
async def test_slash_yolo_switches_level_and_shows_red_badge():
    app = ArgosApp(loop_factory=lambda: FakeLoop())
    async with app.run_test() as pilot:
        await pilot.pause()
        assert app.gate.level is ApprovalLevel.CONFIRM
        assert "YOLO" not in app.sub_title
        app.handle_input("/yolo")
        await pilot.pause()
        assert app.gate.level is ApprovalLevel.AUTO
        assert "YOLO" in app.sub_title


@pytest.mark.asyncio
async def test_slash_status_and_cost_write_to_transcript():
    app = ArgosApp(loop_factory=lambda: FakeLoop())
    async with app.run_test() as pilot:
        await pilot.pause()
        app.handle_input("/status")
        app.handle_input("/cost")
        await pilot.pause()
        log = app.query_one("#transcript")
        assert "phase:" in log.rendered_text
        assert "成本" in log.rendered_text or "$" in log.rendered_text


@pytest.mark.asyncio
async def test_unknown_slash_is_reported_not_run_as_goal():
    app = ArgosApp(loop_factory=lambda: FakeLoop())
    async with app.run_test() as pilot:
        await pilot.pause()
        app.handle_input("/frobnicate")
        await pilot.pause()
        log = app.query_one("#transcript")
        assert "未知命令" in log.rendered_text


# ── final review 回归:两个 HIGH ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_loop_exception_degrades_to_error_not_crash():
    """HIGH:loop.run 抛异常时,_produce 捕获并降级为 Error 事件,TUI 不崩溃(诚实上报而非 PANIC)。"""
    app = ArgosApp(loop_factory=lambda: _RaisingLoop())
    async with app.run_test() as pilot:
        await pilot.pause()
        await app.start_run("会抛异常的任务")
        await app.workers.wait_for_complete()
        await pilot.pause()
        log = app.query_one("#transcript")
        # 异常被容纳成 ❌ 错误 行(含异常链),而非 WorkerFailed 击穿 app。
        assert "❌ 错误" in log.rendered_text
        assert "模型 502" in log.rendered_text
        assert "RuntimeError" in log.rendered_text


@pytest.mark.asyncio
async def test_demo_mode_marks_subtitle_and_warns_before_run():
    """HIGH:默认 demo 模式头部常驻 DEMO 标识,且每轮起手 banner 声明假数据(诚实)。"""
    app = ArgosApp(loop_factory=lambda: FakeLoop())  # demo 默认 True
    async with app.run_test() as pilot:
        await pilot.pause()
        assert "DEMO" in app.sub_title
        await app.start_run("演示任务")
        await app.workers.wait_for_complete()
        await pilot.pause()
        log = app.query_one("#transcript")
        assert "演示模式" in log.rendered_text


@pytest.mark.asyncio
async def test_real_loop_has_no_demo_marker():
    """注入真 loop(demo=False)时,DEMO 标识消失 —— 标识与真实状态一致,不撒谎。"""
    app = ArgosApp(loop_factory=lambda: FakeLoop(), demo=False)
    async with app.run_test() as pilot:
        await pilot.pause()
        assert "DEMO" not in app.sub_title


@pytest.mark.asyncio
async def test_input_focused_on_mount_and_receives_typing():
    """回归:启动后输入框必须自动获焦,否则按键被其它可聚焦兄弟抢走,用户打不了任何字。

    注意作用域:run_test() 是 headless,pilot.press() 把合成 Key 事件直接塞进聚焦 widget,
    绕过了 driver 的真实输入管线(Kitty/legacy 协议、转义码解析、IME)。本测试只证明
    "焦点接线 + value 插入逻辑正确",不能证明真实终端里用户敲键能送达——那个失败发生在
    Pilot 跳过的 driver 层(见 test_kitty_keyboard_protocol_disabled_by_default)。"""
    from textual.widgets import Input

    app = ArgosApp(loop_factory=lambda: FakeLoop())
    async with app.run_test() as pilot:
        await pilot.pause()
        prompt = app.query_one("#prompt", Input)
        assert app.focused is prompt, "启动后焦点必须在输入框(#prompt)"
        await pilot.press("h", "i")
        await pilot.pause()
        assert prompt.value == "hi", "聚焦的输入框应接收按键"


@pytest.mark.asyncio
async def test_input_accepts_cjk_characters():
    """回归:输入框能接收汉字(IME 合成后终端送出的字符走与 ASCII 同路径)。"""
    from textual.widgets import Input

    app = ArgosApp(loop_factory=lambda: FakeLoop())
    async with app.run_test() as pilot:
        await pilot.pause()
        prompt = app.query_one("#prompt", Input)
        # 模拟终端把已合成的汉字逐字送达(Textual 以可打印字符 Key 事件插入)。
        for ch in "修个bug":
            await pilot.press(ch)
        await pilot.pause()
        assert prompt.value == "修个bug", "输入框应接收汉字 + ASCII 混排"


# ── 真实终端键盘:driver 层护栏(Pilot headless 测不到,故用进程级断言守默认) ──────────


@pytest.mark.asyncio
async def test_transcript_fills_main_area_not_collapsed():
    """回归(布局):transcript 必须占主区宽度。此前 ArgosApp 无 CSS → Horizontal 退回默认:
    空 RichLog 收缩到 width=1、CostMeter 撑满整宽 → 对话渲染进 1 列宽 transcript,永远空屏
    (事件其实都写进去了只是不可见)。headless 能量几何,故这条守得住(不像 driver 层 Kitty bug)。"""
    app = ArgosApp(loop_factory=lambda: FakeLoop())
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        t = app.query_one("#transcript")
        c = app.query_one("#activity")
        assert t.size.width >= 40, f"transcript 宽度被压塌={t.size.width},对话会隐形"
        assert t.size.height >= 10, f"transcript 高度不足={t.size.height}"
        assert t.size.width > c.size.width, "transcript 是主区,应比活动侧栏宽"


def test_kitty_keyboard_protocol_disabled_by_default():
    """回归(真实终端 driver 层):导入 TUI 包即默认禁用 Kitty 键盘协议。

    Textual 8.2.7 起默认启用 Kitty 协议,部分终端误解析其转义流 → 可打印键送不到
    已聚焦 Input(表现为"打字完全不显示"),而 headless Pilot 在设计上测不到 driver 层。
    这条进程级断言守住"默认禁用"这个真正修复用户问题的开关(textual.constants.
    DISABLE_KITTY_KEY 只认值恰为 '1')。"""
    import importlib
    import os

    import argos_agent.tui

    saved = os.environ.pop("TEXTUAL_DISABLE_KITTY_KEY", None)
    try:
        importlib.reload(argos_agent.tui)  # 重跑包 __init__ 的 setdefault
        assert os.environ.get("TEXTUAL_DISABLE_KITTY_KEY") == "1"
    finally:
        if saved is not None:
            os.environ["TEXTUAL_DISABLE_KITTY_KEY"] = saved
        else:
            os.environ.setdefault("TEXTUAL_DISABLE_KITTY_KEY", "1")


def test_kitty_disable_respects_explicit_user_optin():
    """用户显式设非 '1' 值(opt-in 回 Kitty)时 setdefault 不覆盖 —— 默认安全但不剥夺选择。"""
    import importlib
    import os

    import argos_agent.tui

    os.environ["TEXTUAL_DISABLE_KITTY_KEY"] = "0"
    try:
        importlib.reload(argos_agent.tui)
        assert os.environ.get("TEXTUAL_DISABLE_KITTY_KEY") == "0", "显式用户值必须被尊重"
    finally:
        os.environ["TEXTUAL_DISABLE_KITTY_KEY"] = "1"


@pytest.mark.asyncio
async def test_user_goal_echoed_to_transcript():
    app = ArgosApp(loop_factory=lambda: FakeLoop())
    async with app.run_test() as pilot:
        await pilot.pause()
        await app.start_run("修个 off-by-one")
        await app.workers.wait_for_complete()
        await pilot.pause()
        log = app.query_one("#transcript")
        # FakeLoop 的 assistant token 也会带上 goal 文本,故只断言"包含 goal"会假绿;
        # 这里钉死 '› ' 前缀的用户行(user_line 的真实产物)才证明目标确实回显进了对话流。
        assert "› 修个 off-by-one" in log.rendered_text, "用户目标必须回显进对话流(› 行)"


class _LoopWithStore:
    """带 .store 的最小 loop 替身,供 /resume 取 store 用(不需要真 run)。"""
    def __init__(self, store):
        self.store = store
    async def run(self, goal, session_id):
        if False:
            yield None  # 使其为 async generator


@pytest.mark.asyncio
async def test_resume_switches_to_most_recent_session(tmp_path):
    """/resume:切到最近一次历史会话,使后续任务带回上下文(修『重开窗口不记得上次』)。"""
    from argos_agent.memory.store import ArgosStore
    from argos_agent.tui.widgets.transcript import Transcript

    store = ArgosStore(db_path=str(tmp_path / "r.db"))
    store.ensure_session("old-sess", title="贪吃蛇")
    store.append_message("old-sess", role="user", content="做个贪吃蛇")
    store.append_message("old-sess", role="assistant", content="好的,做完了")

    app = ArgosApp(loop_factory=lambda: _LoopWithStore(store), demo=False)
    async with app.run_test() as pilot:
        await pilot.pause()
        before = app._session_id                 # 启动是全新 uuid session
        log = app.query_one("#transcript", Transcript)
        await app._resume_recent(log)
        await pilot.pause()
        assert app._session_id == "old-sess", "/resume 应把会话切到最近一次历史会话"
        assert app._session_id != before
        assert "已恢复" in log.rendered_text and "2 条历史" in log.rendered_text
    store.close()


@pytest.mark.asyncio
async def test_resume_honest_when_no_history(tmp_path):
    """无历史会话时 /resume 诚实告知,不假装恢复。"""
    from argos_agent.memory.store import ArgosStore
    from argos_agent.tui.widgets.transcript import Transcript

    store = ArgosStore(db_path=str(tmp_path / "empty.db"))
    app = ArgosApp(loop_factory=lambda: _LoopWithStore(store), demo=False)
    async with app.run_test() as pilot:
        await pilot.pause()
        log = app.query_one("#transcript", Transcript)
        await app._resume_recent(log)
        await pilot.pause()
        assert "没有可恢复" in log.rendered_text
    store.close()
