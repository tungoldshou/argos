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

    def __init__(self, *, loop_factory: Callable[[], object] | None = None) -> None:
        super().__init__()
        # loop_factory() 返回一个有 async run(goal, session_id) -> AsyncIterator[Event] 的对象。
        # 默认 FakeLoop(Phase 3 真 AgentLoop 落地后由入口注入真实工厂)。
        self._loop_factory = loop_factory or (lambda: FakeLoop())
        self.gate = ApprovalGate(ApprovalLevel.CONFIRM)
        self._step_blocks: dict[int, CodeActionBlock] = {}
        self.sub_title = _BASE_SUBTITLE

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
            self.sub_title = f"{_BASE_SUBTITLE} · ⏻ YOLO(Auto)"
            log.append_line("已切换到 Auto(YOLO)——放手执行,头部红标提示。")
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
        bus = EventBus()
        loop = self._loop_factory()

        async def _produce() -> None:
            try:
                async for ev in loop.run(goal, session_id="tui-session"):
                    await bus.emit(ev)
            finally:
                await bus.close()

        self.run_worker(_produce(), exclusive=False)
        async for ev in bus:
            await self._apply_event(ev)

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
