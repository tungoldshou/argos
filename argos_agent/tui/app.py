"""Argos TUI 主屏(spec §4.1)。

布局:Header(含 YOLO 徽标) + Transcript(主对话) + ActivityPanel(右侧活动栏) + StatusBar(always-on) + Input。
事件桥:start_run 起一个 EventBus + 注入的 loop,Worker async-for 消费 Event 并更新 widget(契约 §1/§3)。
slash:输入以 / 开头走 commands.parse_slash 分发;否则当 goal 起一轮 run。
审批:loop 投 ApprovalRequest → push ApprovalModal → 回调里 gate.respond(契约 §6.3)。
"""
from __future__ import annotations

import uuid
from collections.abc import Callable

from textual.app import App, ComposeResult
from textual.containers import Horizontal
from textual.widgets import Footer, Header, Input

from argos_agent.approval import ApprovalGate, ApprovalLevel
from argos_agent.tui.commands import SlashCommand, parse_slash
from argos_agent.tui.events import (
    ApprovalRequest,
    ApprovalResponse,
    CodeAction,
    CodeResult,
    CostUpdate,
    Error,
    Escalation,
    Event,
    EventBus,
    FileDiff,
    PhaseChange,
    TokenDelta,
    ToolReceipt,
    VerifyVerdict,
)
from argos_agent.tui.fakeloop import FakeLoop
from argos_agent.tui.theme import ARGOS_NIGHT
from argos_agent.tui.widgets.activity_panel import ActivityPanel
from argos_agent.tui.widgets.approval_modal import ApprovalModal
from argos_agent.tui.widgets.code_action import CodeActionBlock
from argos_agent.tui.widgets.diff_view import DiffView
from argos_agent.tui.widgets.splash import StartupSplash
from argos_agent.tui.widgets.status_bar import StatusBar
from argos_agent.tui.widgets.thinking import ThinkingIndicator
from argos_agent.tui.widgets.transcript import Transcript
from argos_agent.tui.widgets.verdict_badge import VerdictBadge

_BASE_SUBTITLE = "诚实可靠的终端编码智能体"


class ArgosApp(App):
    TITLE = "Argos"

    # 布局 CSS(spec §4.1:主对话区 + 右侧活动栏)。没有它时 Horizontal 退回 Textual 默认:
    # 空 Transcript 收缩到 width=1、侧栏撑满整宽 → 对话内容渲染进 1 列宽的 transcript,
    # 用户看到的永远是空屏(事件其实都写进去了,只是不可见)。这里显式分配:transcript 占满
    # 剩余宽度(1fr);ActivityPanel 的固定窄栏宽度/左描边由其 DEFAULT_CSS 承担。
    CSS = """
    Screen { border: round #3c3c46; }
    #transcript {
        width: 1fr;
        height: 1fr;
    }
    #activity {
        height: 1fr;
        display: block;
    }
    #prompt { border: tall $primary; }
    ArgosApp.-narrow #activity { display: none; }
    """

    # 窄屏(<90 列)折叠右侧活动栏,把整宽让给对话(Task 14:响应式)。
    HORIZONTAL_BREAKPOINTS = [(0, "-narrow"), (90, "-wide")]

    # 启动/换屏后由 Textual 自动把焦点放到输入框(声明式,框架在正确时机执行)——
    # 否则默认聚焦第一个可聚焦 widget。Transcript 已 can_focus=False 不抢焦点,
    # 这里仍显式声明作双保险。与 on_mount 的手动 focus 一致。
    AUTO_FOCUS = "#prompt"

    BINDINGS = [("ctrl+c", "quit", "退出")]

    def __init__(
        self, *, loop_factory: Callable[[], object] | None = None, demo: bool = True,
        premium: bool = False,
    ) -> None:
        super().__init__()
        # premium=True 用 premium(Claude)档,否则 worker(便宜)档 —— 决定活动栏显示哪个真实模型名。
        self._premium = premium
        # loop_factory() 返回一个有 async run(goal, session_id) -> AsyncIterator[Event] 的对象。
        # 默认 FakeLoop(Phase 6 真 AgentLoop 落地后由入口注入真实工厂)。
        self._loop_factory = loop_factory or (lambda: FakeLoop())
        # demo=True:当前驱动 FakeLoop,产出脚本化假数据 —— 头部常驻 DEMO 标识 + 每轮起手 banner
        # 都如实标注(诚实灵魂:任何脚本化全绿不得在无标识下冒充真实执行)。注入真 loop 时传 demo=False。
        self._demo = demo
        self.gate = ApprovalGate(ApprovalLevel.CONFIRM)
        self._step_blocks: dict[int, CodeActionBlock] = {}
        self._run_active = False
        self._yolo = False
        # 每个 app 实例(=一段会话)用独立稳定 session_id —— loop 跨轮据它从 store 加载历史
        # (多轮上下文)。/clear 换新 id = 开新会话、断上下文。uuid 避免硬编码 "tui-session"
        # 致不同会话共享同一持久化线程。
        self._session_id = uuid.uuid4().hex
        self.sub_title = self._compose_subtitle()

    def _compose_subtitle(self) -> str:
        """头部副标题 = 基底 + DEMO 标识(脚本演示,demo 模式常驻)+ YOLO 标识(Auto 档)。
        DEMO 标识诚实告知"这不是真 agent 在跑";真 loop 注入(demo=False)后自动消失。"""
        parts = [_BASE_SUBTITLE]
        if self._demo:
            parts.append("· DEMO 脚本演示(真 loop 待 Phase 6 接入)")
        if self._yolo:
            parts.append("· ⏻ YOLO(Auto)")
        return "  ".join(parts)

    def compose(self) -> ComposeResult:
        from argos_agent import config
        yield Header()
        with Horizontal():
            yield Transcript(id="transcript")
            tier = config.PREMIUM_TIER if self._premium else config.WORKER_TIER
            yield ActivityPanel(id="activity", model_label=tier.model, tier=tier.name)
        yield StatusBar(id="status-bar")
        yield Input(placeholder="› 输入目标,或 / 开始命令", id="prompt")
        yield Footer()

    def on_mount(self) -> None:
        """启动即把焦点放到输入框。否则 Textual 默认聚焦第一个可聚焦 widget。Transcript 已
        can_focus=False(不抢焦点),但仍显式 focus 输入框作双保险,杜绝任何可聚焦兄弟
        排在 Input 之前抢走按键、用户在输入框打不了字(汉字/ASCII 都进不去)。与 AUTO_FOCUS 双保险。"""
        self.register_theme(ARGOS_NIGHT)
        self.theme = "argos-night"
        self.query_one("#prompt", Input).focus()
        from argos_agent import config
        tier = config.PREMIUM_TIER if self._premium else config.WORKER_TIER
        self.query_one("#transcript", Transcript).mount(
            StartupSplash(model_label=tier.model, tier=tier.name, live=not self._demo)
        )
        # 工作态边缘光(Task 13):idle 灭=中性灰;run 期间随真实阶段着色。纯事件驱动——
        # 颜色只在 PhaseChange/VerifyVerdict/Escalation/Error 真事件到达时变;不用空转计时器
        # (无呼吸动画可演时,定时重设同色既是 CPU churn 又踩 Textual 重绘缓存坑)。
        # 终态告警色(failed/unverifiable/escalation/error)锁定后,阶段色不得覆盖(诚实:告警不被 report 抹掉)。
        self._terminal_glow = False

    # ── 工作态边缘光(spec §工作态边缘光) ─────────────────────────────────
    def _set_border(self, color) -> None:
        self.screen.styles.border = ("round", color)

    def _glow_start(self) -> None:
        from argos_agent.tui import glow
        self._terminal_glow = False           # 新一轮:解锁告警色
        self._set_border(glow.phase_color("plan"))

    def _glow_stop(self) -> None:
        from argos_agent.tui import glow
        self._set_border(glow.IDLE_BORDER)

    # ── 输入分发 ──────────────────────────────────────────────────────────
    def on_input_submitted(self, event: Input.Submitted) -> None:
        text = event.value
        self.query_one("#prompt", Input).value = ""
        self.handle_input(text)

    def handle_input(self, text: str) -> None:
        """slash 走分发;否则当 goal。同步入口(测试可直接调)。

        Transcript 落行是 async,故 slash 分发与"任务进行中"提示都包成 worker(测试 pause 后可见)。"""
        cmd = parse_slash(text)
        if cmd is None:
            if text.strip():
                if self._run_active:
                    # 单会话编码 agent:一轮未完不并发起新轮(否则 step 块串台/漏渲染)。
                    self.run_worker(
                        self.query_one("#transcript", Transcript).append_line(
                            "⏳ 当前任务进行中,请等它结束再起新任务。"
                        ),
                        exclusive=False,
                    )
                    return
                # 非测试同步场景:起一轮 run(测试用 start_run 显式 await)
                self.run_worker(self.start_run(text.strip()), exclusive=False)
            return
        self.run_worker(self._dispatch_slash(cmd), exclusive=False)

    async def _dispatch_slash(self, cmd: SlashCommand) -> None:
        log = self.query_one("#transcript", Transcript)
        if not cmd.known:
            await log.append_line(f"未知命令 /{cmd.name}")
            return
        if cmd.name == "yolo":
            self.gate.set_level(ApprovalLevel.AUTO)
            self._yolo = True
            self.sub_title = self._compose_subtitle()
            await log.append_line("已切换到 Auto(YOLO)——放手执行,头部显示 ⏻ YOLO 标记。")
        elif cmd.name == "model":
            tier = cmd.arg or "(当前)"
            await log.append_line(f"模型切换:{tier}(多模型支持在后续子项目落地)")
        elif cmd.name == "status":
            bar = self.query_one("#status-bar", StatusBar)
            await log.append_line(bar.render_text)
        elif cmd.name == "cost":
            # CostMeter 已退役为活动栏内的"成本 + 缓存"区;/cost 直接回显该区当前正文。
            ap = self.query_one("#activity", ActivityPanel)
            await log.append_line("成本 + 缓存\n" + ap.snapshot_text())
        elif cmd.name == "clear":
            await log.clear()
            self._step_blocks.clear()
            self._session_id = uuid.uuid4().hex  # 换新 session = 开新会话、断多轮上下文。
            await log.append_line("已开新会话(clear)。")
        elif cmd.name in ("undo", "retry", "resume"):
            await log.append_line(f"/{cmd.name} 将在持久化(Phase 2)/loop(Phase 3)接线后生效。")

    # ── 一轮 run:EventBus + loop + Worker 消费 ────────────────────────────
    async def start_run(self, goal: str) -> None:
        if self._run_active:
            return
        self._run_active = True
        self._glow_start()
        for sp in self.query(StartupSplash):
            await sp.remove()
        self._step_blocks = {}  # 每轮独立,杜绝跨轮 step 串台。
        self.query_one("#activity", ActivityPanel).reset_run()  # 每轮起手清活动栏(进度/工具/回执)。
        bus = EventBus()
        loop = self._loop_factory()
        log = self.query_one("#transcript", Transcript)
        await log.user_line(goal)  # 回显用户目标进对话流(› 行),否则对话看着单边(Task 14)。
        if self._demo:
            # 诚实:演示模式每轮起手就声明以下全是脚本假数据,绝不冒充真实执行/验证。
            await log.append_line(
                "⚠️ 演示模式:以下为脚本化假数据,非真实执行/验证(真 AgentLoop 待 Phase 6 接入)。"
            )
        else:
            # 真模式即时回执:M3 plan 阶段推理要数秒,这期间若 transcript 全空,用户会以为
            # "回车没反应"。先落一行"思考中",让用户确认目标已收到、agent 正在跑。
            await log.show_thinking("已收到目标,思考中…")

        async def _produce() -> None:
            try:
                async for ev in loop.run(goal, session_id=self._session_id):
                    await bus.emit(ev)
            except Exception as e:  # noqa: BLE001 — loop 任何异常都降级为 Error 事件,绝不让 TUI 崩溃
                chain: list[str] = []
                cur: BaseException | None = e
                while cur is not None and len(chain) < 4:
                    chain.append(f"{type(cur).__name__}: {cur}")
                    cur = cur.__cause__ or cur.__context__
                await bus.emit(Error(message=str(e), chain=chain))
            finally:
                await bus.close()

        self.run_worker(_produce(), exclusive=False)
        try:
            async for ev in bus:
                await self._apply_event(ev)
        finally:
            # 兜底落定:append_token 把流式尾段滞留 current 气泡,只在 PhaseChange/append_line 落定。
            # 一轮结束时强制落定残余,杜绝"模型最后一句没换行 → 永远不计入 rendered_text"的隐形吞字。
            log.finalize_response()
            self._run_active = False
            self._glow_stop()

    async def _apply_event(self, ev: Event) -> None:
        """把一个契约 §1 Event 反映到对应 widget(一份事件三用的 UI 出口)。"""
        from argos_agent.tui import glow
        log = self.query_one("#transcript", Transcript)
        bar = self.query_one("#status-bar", StatusBar)
        ap = self.query_one("#activity", ActivityPanel)
        if isinstance(ev, TokenDelta):
            await log.append_token(ev.text)
        elif isinstance(ev, PhaseChange):
            for sp in log.query(ThinkingIndicator):
                sp.set_label({"plan": "规划中…", "act": "执行中…", "verify": "验证中…", "report": "汇总中…"}.get(ev.phase, "思考中…"))
            log.finalize_response()
            bar.set_phase(ev.phase, ev.actions)
            ap.on_phase(ev.phase, ev.actions)
            if not self._terminal_glow:        # 终态告警色锁定时阶段色不得覆盖(红/琥珀不被 report 抹掉)
                self._set_border(glow.phase_color(ev.phase))
        elif isinstance(ev, CodeAction):
            block = CodeActionBlock(code=ev.code, step=ev.step)
            self._step_blocks[ev.step] = block
            await log.mount_block(block)
        elif isinstance(ev, CodeResult):
            block = self._step_blocks.get(ev.step)
            if block is not None:
                block.set_result(stdout=ev.stdout, value_repr=ev.value_repr, exc=ev.exc, ok=ev.ok)
        elif isinstance(ev, FileDiff):
            await log.mount_block(DiffView(path=ev.path, added=ev.added, removed=ev.removed, unified=ev.unified))
        elif isinstance(ev, VerifyVerdict):
            existing = list(self.query(VerdictBadge))
            if existing:
                badge = existing[0]
            else:
                badge = VerdictBadge(id="verdict-badge")
                await log.mount_block(badge)
            badge.show(ev.verdict)
            self._set_border(glow.verdict_color(ev.verdict.status))
            if ev.verdict.status in ("failed", "unverifiable"):
                self._terminal_glow = True     # 锁定告警色,后续 report 阶段色不得覆盖
        elif isinstance(ev, CostUpdate):
            bar.set_cost(
                tokens_in=ev.tokens_in, tokens_out=ev.tokens_out,
                cost_usd=ev.cost_usd, elapsed_s=ev.elapsed_s,
            )
            ap.on_cost(
                tokens_in=ev.tokens_in, tokens_out=ev.tokens_out,
                cost_usd=ev.cost_usd, elapsed_s=ev.elapsed_s, cache_read=ev.cache_read,
            )
            from argos_agent import config
            window = (config.PREMIUM_TIER if self._premium else config.WORKER_TIER).context_window
            ap.on_context(used=ev.context_used, window=window)
        elif isinstance(ev, ToolReceipt):
            # 回执进活动栏面板的"回执"区 + 工具计数,不再进 transcript(Task 10)。
            ap.on_receipt(ev.receipt.action)
        elif isinstance(ev, ApprovalRequest):
            await self._handle_approval(ev)
        elif isinstance(ev, ApprovalResponse):
            await log.append_line(f"审批结果:{ev.call_id} → {ev.decision}")
        elif isinstance(ev, Escalation):
            await log.append_line(f"⚠️ 卡住({ev.attempts} 轮):{ev.reason} — 最后失败:{ev.last_failure}", kind="escalation")
            self._set_border(glow.ERROR)
            self._terminal_glow = True
        elif isinstance(ev, Error):
            chain = (" ← " + " ← ".join(ev.chain)) if ev.chain else ""
            await log.append_line(f"❌ 错误:{ev.message}{chain}", kind="error")
            self._set_border(glow.ERROR)
            self._terminal_glow = True

    async def _handle_approval(self, req: ApprovalRequest) -> None:
        """Auto 档不弹窗直接 always;否则弹 ApprovalModal,回调里 respond。"""
        if self.gate.level is ApprovalLevel.AUTO:
            self.gate.respond(req.call_id, "always")
            return

        def _cb(decision: str | None) -> None:
            d = decision or "deny"
            self.gate.respond(req.call_id, d)  # type: ignore[arg-type]
            # append_line 是 async,回调是同步的 → 包成 worker 落行。
            self.run_worker(
                self.query_one("#transcript", Transcript).append_line(
                    f"审批结果:{req.action} → {d}"
                ),
                exclusive=False,
            )

        await self.push_screen(ApprovalModal(req), _cb)
