"""Argos TUI 主屏(spec §4.1)。

布局:Header(含 YOLO 徽标) + TranscriptLog(主对话) + CostMeter(侧栏) + StatusBar(always-on) + Input。
事件桥:start_run 起一个 EventBus + 注入的 loop,Worker async-for 消费 Event 并更新 widget(契约 §1/§3)。
slash:输入以 / 开头走 commands.parse_slash 分发;否则当 goal 起一轮 run。
审批:loop 投 ApprovalRequest → push ApprovalModal → 回调里 gate.respond(契约 §6.3)。
"""
from __future__ import annotations

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
from argos_agent.tui.widgets.approval_modal import ApprovalModal
from argos_agent.tui.widgets.code_action import CodeActionBlock
from argos_agent.tui.widgets.cost_meter import CostMeter
from argos_agent.tui.widgets.diff_view import DiffView
from argos_agent.tui.widgets.status_bar import StatusBar
from argos_agent.tui.widgets.transcript import TranscriptLog
from argos_agent.tui.widgets.verdict_badge import VerdictBadge

_BASE_SUBTITLE = "诚实可靠的终端编码智能体"


class ArgosApp(App):
    TITLE = "Argos"

    BINDINGS = [("ctrl+c", "quit", "退出")]

    def __init__(
        self, *, loop_factory: Callable[[], object] | None = None, demo: bool = True
    ) -> None:
        super().__init__()
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
        yield Header()
        with Horizontal():
            yield TranscriptLog(id="transcript")
            yield CostMeter(id="cost-meter")
        yield StatusBar(id="status-bar")
        yield Input(placeholder="› 输入目标,或 / 开始命令", id="prompt")
        yield Footer()

    # ── 输入分发 ──────────────────────────────────────────────────────────
    def on_input_submitted(self, event: Input.Submitted) -> None:
        text = event.value
        self.query_one("#prompt", Input).value = ""
        self.handle_input(text)

    def handle_input(self, text: str) -> None:
        """slash 走分发;否则当 goal。同步入口(测试可直接调)。"""
        cmd = parse_slash(text)
        if cmd is None:
            if text.strip():
                if self._run_active:
                    # 单会话编码 agent:一轮未完不并发起新轮(否则 step 块串台/漏渲染)。
                    self.query_one("#transcript", TranscriptLog).append_line(
                        "⏳ 当前任务进行中,请等它结束再起新任务。"
                    )
                    return
                # 非测试同步场景:起一轮 run(测试用 start_run 显式 await)
                self.run_worker(self.start_run(text.strip()), exclusive=False)
            return
        self._dispatch_slash(cmd)

    def _dispatch_slash(self, cmd: SlashCommand) -> None:
        log = self.query_one("#transcript", TranscriptLog)
        if not cmd.known:
            log.append_line(f"未知命令 /{cmd.name}")
            return
        if cmd.name == "yolo":
            self.gate.set_level(ApprovalLevel.AUTO)
            self._yolo = True
            self.sub_title = self._compose_subtitle()
            log.append_line("已切换到 Auto(YOLO)——放手执行,头部显示 ⏻ YOLO 标记。")
        elif cmd.name == "model":
            tier = cmd.arg or "worker"
            log.append_line(f"模型切档:{tier}(真切档在 Phase 4 ModelClient 落地)")
        elif cmd.name == "status":
            bar = self.query_one("#status-bar", StatusBar)
            log.append_line(bar.render_text)
        elif cmd.name == "cost":
            meter = self.query_one("#cost-meter", CostMeter)
            log.append_line(meter.render_text)
        elif cmd.name == "clear":
            log.clear()
            self._step_blocks.clear()
            log.append_line("已开新会话(clear)。")
        elif cmd.name in ("undo", "retry", "resume"):
            log.append_line(f"/{cmd.name} 将在持久化(Phase 2)/loop(Phase 3)接线后生效。")

    # ── 一轮 run:EventBus + loop + Worker 消费 ────────────────────────────
    async def start_run(self, goal: str) -> None:
        if self._run_active:
            return
        self._run_active = True
        self._step_blocks = {}  # 每轮独立,杜绝跨轮 step 串台。
        bus = EventBus()
        loop = self._loop_factory()
        log = self.query_one("#transcript", TranscriptLog)
        if self._demo:
            # 诚实:演示模式每轮起手就声明以下全是脚本假数据,绝不冒充真实执行/验证。
            log.append_line(
                "⚠️ 演示模式:以下为脚本化假数据,非真实执行/验证(真 AgentLoop 待 Phase 6 接入)。"
            )

        async def _produce() -> None:
            try:
                async for ev in loop.run(goal, session_id="tui-session"):
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
            self._run_active = False

    async def _apply_event(self, ev: Event) -> None:
        """把一个契约 §1 Event 反映到对应 widget(一份事件三用的 UI 出口)。"""
        log = self.query_one("#transcript", TranscriptLog)
        bar = self.query_one("#status-bar", StatusBar)
        if isinstance(ev, TokenDelta):
            log.append_token(ev.text)
        elif isinstance(ev, PhaseChange):
            log.flush()
            bar.set_phase(ev.phase, ev.actions)
        elif isinstance(ev, CodeAction):
            block = CodeActionBlock(code=ev.code, step=ev.step)
            self._step_blocks[ev.step] = block
            await log.mount(block)
        elif isinstance(ev, CodeResult):
            block = self._step_blocks.get(ev.step)
            if block is not None:
                block.set_result(stdout=ev.stdout, value_repr=ev.value_repr, exc=ev.exc, ok=ev.ok)
        elif isinstance(ev, FileDiff):
            await log.mount(DiffView(path=ev.path, added=ev.added, removed=ev.removed, unified=ev.unified))
        elif isinstance(ev, VerifyVerdict):
            existing = list(self.query(VerdictBadge))
            if existing:
                badge = existing[0]
            else:
                badge = VerdictBadge(id="verdict-badge")
                await log.mount(badge)
            badge.show(ev.verdict)
        elif isinstance(ev, CostUpdate):
            bar.set_cost(
                tokens_in=ev.tokens_in, tokens_out=ev.tokens_out,
                cost_usd=ev.cost_usd, elapsed_s=ev.elapsed_s,
            )
            self.query_one("#cost-meter", CostMeter).update_cost(
                tokens_in=ev.tokens_in, tokens_out=ev.tokens_out,
                cost_usd=ev.cost_usd, elapsed_s=ev.elapsed_s,
            )
        elif isinstance(ev, ToolReceipt):
            log.append_line(f"🧾 receipt: {ev.receipt.action} (已签名)")
        elif isinstance(ev, ApprovalRequest):
            await self._handle_approval(ev)
        elif isinstance(ev, ApprovalResponse):
            log.append_line(f"审批结果:{ev.call_id} → {ev.decision}")
        elif isinstance(ev, Escalation):
            log.append_line(f"⚠️ 卡住({ev.attempts} 轮):{ev.reason} — 最后失败:{ev.last_failure}")
        elif isinstance(ev, Error):
            chain = (" ← " + " ← ".join(ev.chain)) if ev.chain else ""
            log.append_line(f"❌ 错误:{ev.message}{chain}")

    async def _handle_approval(self, req: ApprovalRequest) -> None:
        """Auto 档不弹窗直接 always;否则弹 ApprovalModal,回调里 respond。"""
        if self.gate.level is ApprovalLevel.AUTO:
            self.gate.respond(req.call_id, "always")
            return

        def _cb(decision: str | None) -> None:
            d = decision or "deny"
            self.gate.respond(req.call_id, d)  # type: ignore[arg-type]
            self.query_one("#transcript", TranscriptLog).append_line(
                f"审批结果:{req.action} → {d}"
            )

        await self.push_screen(ApprovalModal(req), _cb)
