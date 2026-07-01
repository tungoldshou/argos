"""Phase 5 端到端接线:FakeLoop 投全套 Event → 各 widget 出现/更新(Pilot)。
覆盖契约不变量:UI 看到的 = 事件源(一份事件三用的 UI 出口)。"""
from __future__ import annotations

import pytest

from argos.approval import ApprovalLevel
from argos.core.types import Verdict
from argos.tui.app import ArgosApp
from argos.tui.events import MemoryRecallEvent, PhaseChange, TokenDelta, VerifyVerdict
from argos.tui.fakeloop import FakeLoop, FailingFakeLoop
from argos.tui.widgets.code_action import CodeActionBlock
from argos.tui.widgets.diff_view import DiffView
from argos.tui.widgets.status_bar import StatusBar
from argos.tui.widgets.verdict_badge import VerdictBadge


class _RaisingLoop:
    """yield 一个事件后抛异常 —— 验证 _produce 把异常降级成 Error 事件而非击穿 TUI(final review HIGH)。"""

    async def run(self, goal, session_id):
        yield PhaseChange(phase="act", actions=1)
        yield TokenDelta(text="干活中...\n")
        raise RuntimeError("模型 502 / sandbox 崩了")


@pytest.mark.asyncio
async def test_app_boots_with_status_bar_and_transcript():
    app = ArgosApp(loop_factory=lambda **kw: FakeLoop())
    async with app.run_test() as pilot:
        await pilot.pause()
        assert app.query_one("#transcript") is not None
        assert app.query_one("#status-bar", StatusBar) is not None
        assert "Argos" in app.title


@pytest.mark.asyncio
async def test_run_goal_drives_widgets_from_events():
    app = ArgosApp(loop_factory=lambda **kw: FakeLoop())
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
        # C2(2026-06-22):run 收尾后 phase 复位 idle —— 不再粘在 'report' 与右栏 idle 互相矛盾。
        # 事件确实驱动过各 widget 由上面的 CodeActionBlock/DiffView/VerdictBadge(passed) 佐证。
        # 去重(2026-07-01):成本/token 归右侧 ActivityPanel,底栏 render_text 不再含。
        assert bar.phase == "idle"
        assert "$" not in bar.render_text and "12.4k" not in bar.render_text


@pytest.mark.asyncio
async def test_failing_run_shows_escalation_and_failed_verdict():
    app = ArgosApp(loop_factory=lambda **kw: FailingFakeLoop())
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
    app = ArgosApp(loop_factory=lambda **kw: FakeLoop())
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
    app = ArgosApp(loop_factory=lambda **kw: FakeLoop())
    async with app.run_test() as pilot:
        await pilot.pause()
        app.handle_input("/status")
        app.handle_input("/cost")
        await pilot.pause()
        log = app.query_one("#transcript")
        # TUI v3 状态眼:/status 回显含阶段名(idle)与动作计数("动作N",⚙ 字形已处决,spec §4.9)
        assert "idle" in log.rendered_text and "动作" in log.rendered_text
        assert "成本" in log.rendered_text or "$" in log.rendered_text


@pytest.mark.asyncio
async def test_unknown_slash_is_reported_not_run_as_goal():
    app = ArgosApp(loop_factory=lambda **kw: FakeLoop())
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
    app = ArgosApp(loop_factory=lambda **kw: _RaisingLoop())
    async with app.run_test() as pilot:
        await pilot.pause()
        await app.start_run("会抛异常的任务")
        await app.workers.wait_for_complete()
        await pilot.pause()
        log = app.query_one("#transcript")
        # 异常被容纳成 ◉ 错误 行(含异常链,v3 字形),而非 WorkerFailed 击穿 app。
        assert "◉ 错误" in log.rendered_text
        assert "模型 502" in log.rendered_text
        assert "RuntimeError" in log.rendered_text


@pytest.mark.asyncio
async def test_input_focused_on_mount_and_receives_typing():
    """回归:启动后输入框必须自动获焦,否则按键被其它可聚焦兄弟抢走,用户打不了任何字。

    注意作用域:run_test() 是 headless,pilot.press() 把合成 Key 事件直接塞进聚焦 widget,
    绕过了 driver 的真实输入管线(Kitty/legacy 协议、转义码解析、IME)。本测试只证明
    "焦点接线 + 字符插入逻辑正确",不能证明真实终端里用户敲键能送达——那个失败发生在
    Pilot 跳过的 driver 层(见 test_kitty_keyboard_protocol_disabled_by_default)。"""
    from argos.tui.widgets.prompt import PromptArea

    app = ArgosApp(loop_factory=lambda **kw: FakeLoop())
    async with app.run_test() as pilot:
        await pilot.pause()
        prompt = app.query_one("#prompt", PromptArea)
        assert app.focused is prompt, "启动后焦点必须在输入框(#prompt)"
        await pilot.press("h", "i")
        await pilot.pause()
        assert prompt.text == "hi", "聚焦的输入框应接收按键"


@pytest.mark.asyncio
async def test_input_accepts_cjk_characters():
    """回归:输入框能接收汉字(IME 合成后终端送出的字符走与 ASCII 同路径)。"""
    from argos.tui.widgets.prompt import PromptArea

    app = ArgosApp(loop_factory=lambda **kw: FakeLoop())
    async with app.run_test() as pilot:
        await pilot.pause()
        prompt = app.query_one("#prompt", PromptArea)
        # 模拟终端把已合成的汉字逐字送达(Textual 以可打印字符 Key 事件插入)。
        for ch in "修个bug":
            await pilot.press(ch)
        await pilot.pause()
        assert prompt.text == "修个bug", "输入框应接收汉字 + ASCII 混排"


# ── 真实终端键盘:driver 层护栏(Pilot headless 测不到,故用进程级断言守默认) ──────────


@pytest.mark.asyncio
async def test_transcript_fills_main_area_not_collapsed():
    """回归(布局):transcript 必须占主区宽度。此前 ArgosApp 无 CSS → Horizontal 退回默认:
    空 RichLog 收缩到 width=1、CostMeter 撑满整宽 → 对话渲染进 1 列宽 transcript,永远空屏
    (事件其实都写进去了只是不可见)。headless 能量几何,故这条守得住(不像 driver 层 Kitty bug)。"""
    app = ArgosApp(loop_factory=lambda **kw: FakeLoop())
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

    import argos.tui

    saved = os.environ.pop("TEXTUAL_DISABLE_KITTY_KEY", None)
    try:
        importlib.reload(argos.tui)  # 重跑包 __init__ 的 setdefault
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

    import argos.tui

    os.environ["TEXTUAL_DISABLE_KITTY_KEY"] = "0"
    try:
        importlib.reload(argos.tui)
        assert os.environ.get("TEXTUAL_DISABLE_KITTY_KEY") == "0", "显式用户值必须被尊重"
    finally:
        os.environ["TEXTUAL_DISABLE_KITTY_KEY"] = "1"


@pytest.mark.asyncio
async def test_user_goal_echoed_to_transcript():
    app = ArgosApp(loop_factory=lambda **kw: FakeLoop())
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
    from argos.memory.store import ArgosStore
    from argos.tui.widgets.transcript import Transcript

    store = ArgosStore(db_path=str(tmp_path / "r.db"))
    store.ensure_session("old-sess", title="贪吃蛇")
    store.append_message("old-sess", role="user", content="做个贪吃蛇")
    store.append_message("old-sess", role="assistant", content="好的,做完了")

    app = ArgosApp(loop_factory=lambda **kw: _LoopWithStore(store))
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
    from argos.memory.store import ArgosStore
    from argos.tui.widgets.transcript import Transcript

    store = ArgosStore(db_path=str(tmp_path / "empty.db"))
    app = ArgosApp(loop_factory=lambda **kw: _LoopWithStore(store))
    async with app.run_test() as pilot:
        await pilot.pause()
        log = app.query_one("#transcript", Transcript)
        await app._resume_recent(log)
        await pilot.pause()
        assert "没有可恢复" in log.rendered_text
    store.close()


# ── P9 新接线(TUI v3 spec §8):Compacted/Pruned 分支 · StatusBar 优先级 · 记忆召回 ─────


@pytest.mark.asyncio
async def test_compacted_event_writes_transcript_line_and_panel():
    """spec §8.1:CompactedEvent → transcript faint 系统行(↯/◌ 压缩 -N% · A→B)+ 右栏上下文区。"""
    from argos.tui.events import CompactedEvent
    script = [
        PhaseChange(phase="act", actions=1),
        CompactedEvent(before=12, after=4, reduction_pct=0.22, triggered_by="proactive"),
    ]
    app = ArgosApp(loop_factory=lambda **kw: FakeLoop(script=script))
    async with app.run_test() as pilot:
        await pilot.pause()
        await app.start_run("压缩任务")
        await app.workers.wait_for_complete()
        await pilot.pause()
        text = app.query_one("#transcript").rendered_text
        # 0-1 分数 → 百分比;诚实显真实条数,不预填
        assert "压缩" in text and "-22%" in text and "12→4" in text


@pytest.mark.asyncio
async def test_pruned_event_writes_transcript_line():
    """spec §8.1:PrunedEvent → transcript faint 系统行(◌ 已修剪 N 条)。"""
    from argos.tui.events import PrunedEvent
    script = [
        PhaseChange(phase="act", actions=1),
        PrunedEvent(before=80, after=60, removed=5, reduction_pct=0.25, aggressiveness=0.5),
    ]
    app = ArgosApp(loop_factory=lambda **kw: FakeLoop(script=script))
    async with app.run_test() as pilot:
        await pilot.pause()
        await app.start_run("修剪任务")
        await app.workers.wait_for_complete()
        await pilot.pause()
        text = app.query_one("#transcript").rendered_text
        assert "修剪" in text and "5 条" in text


@pytest.mark.asyncio
async def test_status_bar_blocked_on_approval_card_then_cleared():
    """spec §8.4 优先级铁律:审批卡 mount → StatusBar set_blocked(True)(左眼 ◓ + "审批挂起");
    决策落定后 set_blocked(False)。用户阻塞态永远赢(即便引擎在跑)。"""
    from argos.tui.events import ApprovalRequest
    from argos.tui.widgets.inline_choice import InlineChoice
    script = [
        PhaseChange(phase="verify", actions=2),   # 引擎在 verify,但用户阻塞应赢
        ApprovalRequest(
            call_id="c1", action="run_command", args={"cmd": "git push"},
            description="soft rule: ask git push", risk="medium", trigger="soft rule",
        ),
    ]
    app = ArgosApp(loop_factory=lambda **kw: FakeLoop(script=script))
    async with app.run_test() as pilot:
        await pilot.pause()
        app.run_worker(app.start_run("要审批的任务"), exclusive=False)
        # 等审批卡 mount(loop 在投 ApprovalRequest 后挂起等 respond)
        for _ in range(40):
            await pilot.pause()
            if list(app.query(InlineChoice)):
                break
        bar = app.query_one("#status-bar", StatusBar)
        assert bar._blocked is True, "审批卡活动时 StatusBar 应进 blocked 态"
        # 优先级铁律:即便 phase==verify,左眼显 ◓ + "审批挂起"
        assert bar.render_text.startswith("◓"), "用户阻塞态左眼应为 ◓(优先级最高)"
        assert "审批挂起" in bar.render_text
        # 用户决策 → respond + 解除挂起
        choice = list(app.query(InlineChoice))[0]
        choice._finish("deny", "")
        await app.workers.wait_for_complete()
        await pilot.pause()
        assert bar._blocked is False, "决策落定后 StatusBar 应解除 blocked 态"


@pytest.mark.asyncio
async def test_status_bar_alert_locked_on_failed_verdict_not_overwritten_by_report():
    """陷阱2(spec §8.4):failed verdict → set_alert(True) 告警锁色;后续 report 阶段
    眼随阶段但整条仍锁 -alert(阶段色/眼不得覆盖告警)。"""
    script = [
        PhaseChange(phase="verify", actions=2),
        VerifyVerdict(verdict=Verdict.failed(detail="1 failed", verify_cmd="pytest", attempts=3)),
        PhaseChange(phase="report", actions=2),   # 陷阱2:report 不得抹掉告警
        TokenDelta(text="诚实上报失败。\n"),
    ]
    app = ArgosApp(loop_factory=lambda **kw: FakeLoop(script=script))
    async with app.run_test() as pilot:
        await pilot.pause()
        await app.start_run("会失败的验证")
        await app.workers.wait_for_complete()
        await pilot.pause()
        bar = app.query_one("#status-bar", StatusBar)
        assert app._terminal_glow is True, "failed verdict 应锁定 _terminal_glow"
        assert bar._alert is True, "陷阱2:report 阶段后告警锁色不得被清(StatusBar -alert 仍在)"
        assert bar.has_class("-alert"), "告警态 CSS 类 -alert 应在"


@pytest.mark.asyncio
async def test_status_bar_alert_cleared_on_new_run():
    """spec §8.4:新 run(_glow_start)解锁告警色——上一轮 failed 的 -alert 不泄漏到下一轮。"""
    fail_script = [
        VerifyVerdict(verdict=Verdict.failed(detail="x", verify_cmd="pytest", attempts=1)),
    ]
    ok_script = [
        PhaseChange(phase="plan", actions=0),
        VerifyVerdict(verdict=Verdict.passed(detail="ok", verify_cmd="pytest", attempts=1)),
    ]
    scripts = iter([fail_script, ok_script])
    app = ArgosApp(loop_factory=lambda **kw: FakeLoop(script=next(scripts)))
    async with app.run_test() as pilot:
        await pilot.pause()
        await app.start_run("第一轮失败")
        await app.workers.wait_for_complete()
        await pilot.pause()
        bar = app.query_one("#status-bar", StatusBar)
        assert bar._alert is True
        # 第二轮:_glow_start 应清告警
        await app.start_run("第二轮成功")
        await app.workers.wait_for_complete()
        await pilot.pause()
        assert app._terminal_glow is False, "新 run 应解锁告警"
        assert bar._alert is False, "新 run 后 StatusBar -alert 应清"


@pytest.mark.asyncio
async def test_memory_recall_line_shown_with_real_store_hits(tmp_path):
    """spec §8.3 + v6 §4 ACP:loop 投 MemoryRecallEvent(hits=[...]) →
    TUI _apply_event 渲染 transcript faint 行 "◌ 记忆召回 N 条";
    诚实:计数取自事件 hits 列表长度,绝不编造。

    v6 P2 改:TUI 不再 getattr(loop,'_store') 穿透;
    loop 经 MemoryRecallEvent 广播召回结果(store 穿透修)。
    """
    class _LoopWithRecallEvent:
        async def run(self, goal, session_id):
            # v6 §4 ACP:loop 在 run() 起始投 MemoryRecallEvent
            yield MemoryRecallEvent(hits=["上次也改过 auth → passed（similar goal）"])
            yield PhaseChange(phase="plan", actions=0)

    app = ArgosApp(loop_factory=lambda **kw: _LoopWithRecallEvent())
    async with app.run_test() as pilot:
        await pilot.pause()
        await app.start_run("改 auth.py")
        await app.workers.wait_for_complete()
        await pilot.pause()
        text = app.query_one("#transcript").rendered_text
        assert "记忆召回 1 条" in text, "真召回到 1 条应如实显示"


@pytest.mark.asyncio
async def test_memory_recall_silent_when_no_store():
    """spec §8.3 诚实边界:demo/FakeLoop 无 store → 不显召回行(没召回别假装召回)。"""
    app = ArgosApp(loop_factory=lambda **kw: FakeLoop())
    async with app.run_test() as pilot:
        await pilot.pause()
        await app.start_run("普通任务")
        await app.workers.wait_for_complete()
        await pilot.pause()
        text = app.query_one("#transcript").rendered_text
        assert "记忆召回" not in text, "无 store 不得谎报召回"


# ── Issue A 回归:_apply_event(PhaseChange) 必须驱动 ap._view ─────────────────────────────────


@pytest.mark.asyncio
async def test_apply_event_phase_change_drives_activity_panel_view():
    """回归(Issue A):_apply_event(PhaseChange(act)) 必须把 ap._view 切到 'act'。

    根因:start_run 的 finally 块调 on_run_end() → set_view('idle'),截图时右栏已回 idle。
    修复:截图脚本改用 _apply_event 直接投事件(不走 start_run),这里验证接线正确。
    断言:事件到达 → ap._view 更新;on_run_end 未调用 → 视图不回退。
    """
    from argos.tui.widgets.activity_panel import ActivityPanel

    app = ArgosApp(loop_factory=lambda **kw: FakeLoop())
    async with app.run_test() as pilot:
        await pilot.pause()
        ap = app.query_one("#activity", ActivityPanel)
        assert ap._view == "idle", "初始视图应为 idle"

        # 直接投 PhaseChange(act) — 不走 start_run
        await app._apply_event(PhaseChange(phase="act", actions=1))
        await pilot.pause()
        assert ap._view == "act", (
            "_apply_event(PhaseChange(act)) 应把 ap._view 切到 'act';"
            " 若仍为 idle 说明 app._apply_event → ap.on_phase 接线断了"
        )

        # 继续投 PhaseChange(verify),视图应跟随
        await app._apply_event(PhaseChange(phase="verify", actions=2))
        await pilot.pause()
        assert ap._view == "verify", "_apply_event(PhaseChange(verify)) 应把视图切到 'verify'"

        # on_run_end 未被调用,视图不应回退
        assert ap._view != "idle", "未调 on_run_end,视图不应回退到 idle"
