"""Argos TUI 主屏(spec §4.1)。

布局:Header(含 YOLO 徽标) + Transcript(主对话) + ActivityPanel(右侧活动栏) + StatusBar(always-on) + Input。
事件桥:start_run 起一个 EventBus + 注入的 loop,Worker async-for 消费 Event 并更新 widget(契约 §1/§3)。
slash:输入以 / 开头走 commands.parse_slash 分发;否则当 goal 起一轮 run。
审批:loop 投 ApprovalRequest → push ApprovalModal → 回调里 gate.respond(契约 §6.3)。
"""
from __future__ import annotations

import uuid
from collections.abc import Callable
from pathlib import Path

from textual.app import App, ComposeResult
from textual.containers import Horizontal
from textual.widgets import Footer, Header

from argos_agent.approval import ApprovalGate, ApprovalLevel
from argos_agent.core.snapshot import SNAPSHOT_ROOT, RunSnapshot
from argos_agent.tui.commands import SlashCommand, match_commands, parse_slash
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
    PlanRendered,
    PlanUpdate,
    TokenDelta,
    ToolReceipt,
    VerifyVerdict,
    WorkflowDone,
    WorkflowProgress,
    WorkflowProposed,
)
from argos_agent.tui.fakeloop import FakeLoop
from argos_agent.tui.theme import ARGOS_NIGHT
from argos_agent.tui.widgets.activity_panel import ActivityPanel
from argos_agent.tui.widgets.approval_modal import ApprovalModal
from argos_agent.tui.widgets.plan_modal import PlanDecision, PlanModal
from argos_agent.tui.widgets.code_action import CodeActionBlock
from argos_agent.tui.widgets.diff_view import DiffView
from argos_agent.tui.widgets.prompt import PromptArea, SlashMenu
from argos_agent.tui.widgets.splash import StartupSplash
from argos_agent.tui.widgets.status_bar import StatusBar
from argos_agent.tui.widgets.thinking import ThinkingIndicator
from argos_agent.tui.widgets.transcript import Transcript
from argos_agent.tui.widgets.verdict_badge import VerdictBadge
from argos_agent.tui.widgets.workflow_approval_modal import WorkflowApprovalModal
from argos_agent.tui.widgets.workflow_panel import WorkflowPanel

_BASE_SUBTITLE = "终端超级智能体"


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

    # Esc 打断当前任务(对齐 Claude Code):取消正在跑的 run。模型推理/等待这类 await 点能即时
    # 中断;若卡在同步 exec_code(命令/浏览器动作占住事件循环)则需等该动作返回后才落地(诚实:
    # 不假装能瞬间杀掉同步子进程)。idle 时按 Esc 无副作用。
    # `Ctrl+B` 后台化(daemon 模式):把当前 run 推到 daemon → state=suspended(可跨 session 续)。
    BINDINGS = [
        ("ctrl+c", "quit", "退出"),
        ("escape", "interrupt", "打断"),
        ("ctrl+b", "background", "后台"),
    ]

    def __init__(
        self, *, loop_factory: Callable[[], object] | None = None, demo: bool = True,
        gate: ApprovalGate | None = None,
    ) -> None:
        super().__init__()
        # 模型不绑定、无档位:活动栏显示的真实模型名取自 config.active_tier()(当前 active profile)。
        # loop_factory() 返回一个有 async run(goal, session_id) -> AsyncIterator[Event] 的对象。
        # 默认 FakeLoop(Phase 6 真 AgentLoop 落地后由入口注入真实工厂)。
        self._loop_factory = loop_factory or (lambda: FakeLoop())
        # demo=True:当前驱动 FakeLoop,产出脚本化假数据 —— 头部常驻 DEMO 标识 + 每轮起手 banner
        # 都如实标注(诚实灵魂:任何脚本化全绿不得在无标识下冒充真实执行)。注入真 loop 时传 demo=False。
        self._demo = demo
        # 给了共享 gate(真 loop 路径:= broker.gate)就用它 —— 这样工作流/工具审批 respond
        # 落在 loop 真正 await 的那个 gate 上(否则打错实例,审批永远不放行)。
        # 没给(demo/fake 路径)自建一个 CONFIRM 档,行为不变。
        self.gate = gate or ApprovalGate(ApprovalLevel.CONFIRM)
        self._step_blocks: dict[int, CodeActionBlock] = {}
        self._workflow_panel: WorkflowPanel | None = None  # 当前工作流的进度树面板(WorkflowProposed 时 mount)
        self._run_active = False
        self._produce_worker = None     # 当前 run 的生产 worker(Esc 打断时取消它)
        self._interrupted = False       # 本轮是否被用户 Esc 打断(收尾时落一行提示)
        self._yolo = False
        # Plan mode spec §2.5:loop 投 PlanRendered 事件时 TUI 推 PlanModal + 在 modal 回调里
        # 调 ExitPlanMode(loop, ...) + set loop._plan_decision_event 唤醒 loop 的 await。
        # 需存本轮 run 的 loop 引用(start_run 是 async 但 loop 是局部变量,事件回调在 _apply_event
        # 拿不到 —— 故暴露在 self 上,每轮 run 起始重设)。
        self._current_loop: object | None = None
        # Plan mode 状态(spec §2.4 视觉指示):_plan_mode=True 时 splash 加 [plan mode] 前缀、
        # status_bar Mode 段切 plan + 改色、sub_title 挂 [plan mode] 标识。set_plan_mode_indicators()
        # 是 host 切换的单入口,/plan → EnterPlanMode 后调它一次,下一轮 start_run 起手也会按它
        # 决定是否落 plan 阶段。
        self._plan_mode = False
        # 每个 app 实例(=一段会话)用独立稳定 session_id —— loop 跨轮据它从 store 加载历史
        # (多轮上下文)。/clear 换新 id = 开新会话、断上下文。uuid 避免硬编码 "tui-session"
        # 致不同会话共享同一持久化线程。
        self._session_id = uuid.uuid4().hex
        # /undo 配套:workspace 根 + run 自增序号 + 本轮 run 起点的快照(供 /undo 还原)。
        # 临时默认,真接 loop 时再校准(见 plan Task 10 校准 note §5)。
        self._workspace: Path = Path.home() / ".argos" / "workspace"
        self._run_seq: int = 0
        self._snapshot: "RunSnapshot | None" = None
        # ── Daemon 模式状态(spec 2026-06-06 §2.6/2.7)────────────────
        # with_daemon=True 启用 daemon 模式:
        #   · DaemonClient 走 Unix socket(本机 ~/.argos/daemon.sock)
        #   · Esc = step-boundary pause(POST /pause)而非直接 kill
        #   · 双 Esc(<1.5s) = cancel
        #   · Ctrl+B = 后台化(POST /suspend)
        #   · 启动时扫 suspended run,弹 inline modal 让用户选
        # 默认 False(legacy TUI-only 行为,沿用旧 Esc=cancel)。
        self._with_daemon: bool = False
        self._daemon_client = None     # type: ignore[var-annotated]
        self._daemon_session_id: str | None = None
        self._daemon_run_id: str | None = None   # 当前 run 在 daemon 里的 run_id
        self._last_esc_time: float = 0.0          # 双 Esc 检测(1.5s 内第二次 = cancel)
        self.sub_title = self._compose_subtitle()

    @staticmethod
    def _display_tier():
        """当前 active 模型的 tier(活动栏/启动画面/上下文窗口显示用);
        配置异常或无 config 时回退 DEFAULT_TIER,绝不崩 UI。无 worker/premium 档位。"""
        from argos_agent import config
        try:
            return config.active_tier()
        except Exception:  # noqa: BLE001
            return config.DEFAULT_TIER

    def _compose_subtitle(self) -> str:
        """头部副标题 = 基底 + DEMO 标识(脚本演示,demo 模式常驻)+ YOLO 标识(Auto 档)+ plan mode 标识。
        DEMO 标识诚实告知"这不是真 agent 在跑";真 loop 注入(demo=False)后自动消失。
        plan mode 标识 [plan mode] 在 /plan 切到后挂上,ExitPlanMode 后摘掉(经 set_plan_mode_indicators)。"""
        parts = [_BASE_SUBTITLE]
        if self._plan_mode:
            parts.append("· [plan mode]")
        if self._demo:
            parts.append("· DEMO 脚本演示(真 loop 待 Phase 6 接入)")
        if self._yolo:
            parts.append("· ⏻ YOLO(Auto)")
        return "  ".join(parts)

    def compose(self) -> ComposeResult:
        yield Header()
        with Horizontal():
            yield Transcript(id="transcript")
            tier = self._display_tier()
            yield ActivityPanel(id="activity", model_label=tier.model, tier=tier.name)
        yield StatusBar(id="status-bar")
        # slash 菜单(默认隐藏)叠在输入框上方:打 / 时列出命令;PromptArea 是多行输入(Enter 提交)。
        yield SlashMenu(id="slash-menu")
        yield PromptArea(placeholder="› 输入目标,或 / 开始命令", id="prompt")
        yield Footer()

    def on_mount(self) -> None:
        """启动即把焦点放到输入框。否则 Textual 默认聚焦第一个可聚焦 widget。Transcript 已
        can_focus=False(不抢焦点),但仍显式 focus 输入框作双保险,杜绝任何可聚焦兄弟
        排在 Input 之前抢走按键、用户在输入框打不了字(汉字/ASCII 都进不去)。与 AUTO_FOCUS 双保险。"""
        self.register_theme(ARGOS_NIGHT)
        self.theme = "argos-night"
        self.query_one("#prompt", PromptArea).focus()
        tier = self._display_tier()
        self.query_one("#transcript", Transcript).mount(
            StartupSplash(model_label=tier.model, tier=tier.name, live=not self._demo)
        )
        # 启动时根据 _plan_mode 状态把指示器对齐(默认 False;若 /plan 已触发过则 True)。
        self._set_plan_mode_indicators()
        # 工作态边缘光(Task 13):idle 灭=中性灰;run 期间随真实阶段着色,并在非终态做呼吸动画。
        # 颜色基色只在 PhaseChange/VerifyVerdict/Escalation/Error 真事件到达时变;呼吸只在该基色上调亮暗。
        # 终态告警色(failed/unverifiable/escalation/error)锁定后,阶段色不得覆盖且不呼吸(诚实:告警静止,不被 report 抹掉)。
        self._terminal_glow = False
        self._glow_base = None          # 当前呼吸基色(None=不呼吸)
        self._glow_phase = 0.0          # 呼吸相位累加器 t∈[0,1]
        self._glow_timer = None
        # 启动时显坏配置 banner(若 ~/.argos/hooks.json 或 lsp.json 或 permissions.json 解析失败)
        try:
            from argos_agent.hooks import reload_config
            reload_config()
        except Exception as e:  # noqa: BLE001 — 坏配置 banner,run 正常起
            for sp in self.query(StartupSplash):
                sp.set_bad_config(str(e))
        try:
            from argos_agent.lsp import reload_config as _lsp_reload_config
            _lsp_reload_config()
        except Exception as e:  # noqa: BLE001 — LSP 坏配置 banner,run 正常起
            for sp in self.query(StartupSplash):
                sp.set_bad_config(f"LSP {e}")
        # Smart approval(spec 2026-06-06 §2.6):启动时 reload + 接 TUI ActivityPanel 决策监听 +
        # 把 workspace 注入 gate 让 evaluator 跑 system path / workspace 边界 check。
        try:
            from argos_agent.permissions import reload_config as _perm_reload_config
            _perm_reload_config()
        except Exception as e:  # noqa: BLE001 — permissions 坏配置 banner,run 正常起
            for sp in self.query(StartupSplash):
                sp.set_bad_config(f"permissions: {e}")
        # gate 接 ActivityPanel 'Approval' 区段(每次评估完触发 listener,UI 实时反映)
        try:
            ap = self.query_one("#activity", ActivityPanel)
            self.gate.set_decision_listener(
                lambda action, decision, trigger: ap.on_approval_decision(
                    action=action, decision=decision, trigger=trigger,
                )
            )
        except Exception:  # noqa: BLE001 — 未 mount 或测试场景:静默
            pass
        # workspace 注入(诚实:_workspace 是 host 启动时计算好的工作目录;evaluator 据此跑边界)
        try:
            self.gate.set_workspace(str(self._workspace))
        except Exception:  # noqa: BLE001
            pass

    # ── 工作态边缘光(spec §工作态边缘光) ─────────────────────────────────
    def _set_border(self, color) -> None:
        self.screen.styles.border = ("round", color)

    def _glow_start(self) -> None:
        from argos_agent.tui import glow
        self._terminal_glow = False           # 新一轮:解锁告警色
        self._glow_phase = 0.0
        self._glow_base = glow.phase_color("plan")
        self._set_border(self._glow_base)
        if self._glow_timer is None:          # 起呼吸计时器(边框色 set_interval 重设,glow 可行性研究已证安全无闪烁)
            self._glow_timer = self.set_interval(0.1, self._glow_breathe)

    def _glow_breathe(self) -> None:
        """非终态时把当前阶段基色按 breathe 调亮暗(呼吸);终态告警色静止不呼吸。"""
        from argos_agent.tui import glow
        if self._terminal_glow or self._glow_base is None:
            return
        self._glow_phase = (self._glow_phase + 0.03) % 1.0   # 步长 0.03/0.1s tick → ~3.3s 一个呼吸周期(平静呼吸,非快速脉冲)
        self._set_border(glow.breathe(self._glow_base, self._glow_phase))

    def _glow_stop(self) -> None:
        from argos_agent.tui import glow
        if self._glow_timer is not None:
            self._glow_timer.stop()
            self._glow_timer = None
        self._glow_base = None
        self._set_border(glow.IDLE_BORDER)

    # ── plan mode 视觉指示(spec §2.4) ─────────────────────────────
    def _set_plan_mode_indicators(self) -> None:
        """按 self._plan_mode 一次性把 splash / status_bar / sub_title 三个指示器对齐。

        host 切 plan mode 的单入口:/plan → EnterPlanMode 后调它一次。
        退出时再调一次(False)摘掉所有 [plan mode] 标记。
        """
        from argos_agent.tui import glow
        for sp in self.query(StartupSplash):
            sp.set_plan_mode(self._plan_mode)
        try:
            self.query_one("#status-bar", StatusBar).set_plan_mode(self._plan_mode)
        except Exception:  # noqa: BLE001 — 测试中或在 on_mount 前调,status_bar 还没 mount,静默
            pass
        self.sub_title = self._compose_subtitle()
        if self._plan_mode and not self._run_active:
            # idle 切 plan mode 时把边框也换到 plan 基色(不呼吸 —— run 期间再由 _glow_start 接管)
            self._set_border(glow.phase_color("plan"))

    # ── 输入分发 ──────────────────────────────────────────────────────────
    def on_prompt_area_submitted(self, event: PromptArea.Submitted) -> None:
        # PromptArea 已在内部清空自身;这里只负责分发(slash / goal)。同时收掉 slash 菜单。
        self.query_one("#slash-menu", SlashMenu).hide()
        self.handle_input(event.text)

    def on_text_area_changed(self, event) -> None:
        """输入内容变化 → 驱动 slash 命令菜单(打 / 即列命令;带参/非 slash 则隐藏)。"""
        menu = self.query_one("#slash-menu", SlashMenu)
        menu.show_matches(match_commands(event.text_area.text))

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
            from argos_agent import config as _cfg
            arg = cmd.arg  # SlashCommand.arg 已是 parse_slash 拆出的参数部分
            if not arg:
                try:
                    profs = _cfg.list_profiles()
                    cur = _cfg.load_config().active if _cfg._has_config_file() else profs[0]
                except Exception:  # noqa: BLE001
                    _fallback = _cfg.DEFAULT_TIER
                    profs, cur = [_fallback.name], _fallback.name
                await log.append_line(
                    "可用模型:" + ", ".join(f"{p}{' *' if p == cur else ''}" for p in profs),
                    kind="system")
            else:
                try:
                    _cfg.set_active(arg)
                    # 诚实:模型在启动时 build_components 注入一次,会话内不热切换;只重启真生效
                    #(不写"新任务生效"——那是假话,会话内新任务仍用旧模型)。
                    await log.append_line(f"已切到 '{arg}'(重启 argos 后生效)。", kind="done")
                except Exception as e:  # noqa: BLE001
                    await log.append_line(f"切换失败:{e}", kind="error")
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
        elif cmd.name == "resume":
            await self._resume_recent(log)
        elif cmd.name == "help":
            from argos_agent.tui.commands import COMMAND_HELP
            lines = ["命令(打 / 也会就地列出,Tab 补全):"]
            lines += [f" · /{name:<8} {desc}" for name, desc in COMMAND_HELP.items()]
            lines.append("快捷键:Esc 打断当前任务 · 行尾 \\ + 回车 换行 · ^C 退出")
            await log.append_line("\n".join(lines), kind="system")
        elif cmd.name == "tools":
            await self._show_tools(log)
        elif cmd.name == "skills":
            await self._show_skills(log)
        elif cmd.name == "mcp":
            await self._show_mcp(log)
        elif cmd.name == "undo":
            await self._undo(log)
        elif cmd.name == "retry":
            await self._retry(log)
        elif cmd.name == "plan":
            await self._enter_plan_mode(log)
        elif cmd.name == "hooks":
            await self._hooks_cmd(log, cmd.arg)
        elif cmd.name == "lsp":
            await self._lsp_cmd(log, cmd.arg)
        elif cmd.name == "permissions":
            await self._permissions_cmd(log, cmd.arg)
        elif cmd.name == "runs":
            await self._runs_cmd(log, cmd.arg)
        elif cmd.name == "verify":
            await self._skill_cmd(log, "verify", cmd.arg)
        elif cmd.name == "security-review":
            await self._skill_cmd(log, "security-review", cmd.arg)
        elif cmd.name == "simplify":
            await self._skill_cmd(log, "simplify", cmd.arg)
        elif cmd.name == "remember":
            await self._remember_cmd(log, cmd.arg)
        elif cmd.name == "forget":
            await self._forget_cmd(log, cmd.arg)
        elif cmd.name == "memory":
            await self._memory_cmd(log)

    async def _undo(self, log) -> None:
        """/undo:用本轮 run 起点的快照还原 workspace;不发 goal。"""
        if self._snapshot is None or not self._snapshot.tar_path.exists():
            await log.append_line(
                "无可撤销的运行(本会话尚未启动 run,或快照已清理)。",
                kind="system",
            )
            return
        result = self._snapshot.restore(self._workspace)
        if result.errors:
            head = "\n".join(f"  ✗ {p}: {e}" for p, e in result.errors[:5])
            more = "\n  …(更多省略)" if len(result.errors) > 5 else ""
            await log.append_line(
                f"部分还原(成功 {len(result.restored)} / 失败 {len(result.errors)}):\n{head}{more}",
                kind="error",
            )
        else:
            await log.append_line(
                f"已还原 {len(result.restored)} 个文件到 run 起点。\n"
                f"如要继续,可 /retry 重发上一条 goal,或输入新 goal。",
                kind="done",
            )

    async def _retry(self, log) -> None:
        """/retry:重发本 session 最后一条 user 消息。busy / 空 / 无 store 诚实报。

        实现简化:demo 模式(FakeLoop,无 store)下诚实报"当前 store 不支持"——
        真模式需要 build_components 把 store 注入到 App(self._store 字段),
        那是更大装配改动,留作下一 PR。
        """
        if self._run_active:  # busy 守卫(实际字段是 _run_active,非 _busy)
            await log.append_line("先 Esc 打断当前任务,再 /retry。", kind="system")
            return
        # store 临时获取:走 loop_factory 拿一个临时 loop 借 .store 属性
        # (实际应通过 build_components 注入;这是 demo 模式下的临时方案)
        loop = self._loop_factory() if self._loop_factory is not None else None
        store = getattr(loop, "store", None) if loop is not None else None
        if store is None or not hasattr(store, "get_messages"):
            await log.append_line("当前 store 不支持 /retry(demo 模式或未通过 build_components 注入)。", kind="error")
            return
        try:
            msgs = store.get_messages(self._session_id)
        except Exception as e:  # noqa: BLE001
            await log.append_line(f"读取历史失败:{e}", kind="error")
            return
        last_user = next(
            (m for m in reversed(msgs) if m.get("role") == "user" and (m.get("text") or "").strip()),
            None,
        )
        if last_user is None:
            await log.append_line("当前会话没有可重试的消息。", kind="system")
            return
        await self.start_run(last_user["text"])

    async def _enter_plan_mode(self, log) -> None:
        """/plan slash 命令入口:把 host 切到 plan mode,让下一轮 run 走 plan 阶段(沙箱工具 dispatcher 守卫会拦截写操作)。

        实现简化:loop factory 拿一个临时 loop(同 Task 5 /retry 注释里"临时方案"一样)调 EnterPlanMode;
        EnterPlanMode 内部 set_plan_mode(True)(模块级) + loop.mode="plan" + 若 loop 有 _emit_phase 则发 PhaseChange。
        FakeLoop 没 _emit_phase → 视觉指示器靠 _set_plan_mode_indicators() 手动对齐(标题/状态栏/边框),
        真 loop 也会被 _set_plan_mode_indicators 覆盖一次以保 splash / status_bar 同步。
        ExitPlanMode 由 host 在 plan 阶段产出 plan 文档后弹 PlanModal 取 4 选项,本方法不接管审批 modal 推屏。
        """
        from argos_agent.core.plan_mode import EnterPlanMode
        try:
            loop = self._loop_factory()
        except Exception as e:  # noqa: BLE001 — loop 工厂抛(配错/无依赖)也落行告知,不崩 TUI
            await log.append_line(f"/plan 不可用(loop factory 失败):{e}", kind="error")
            return
        msg = EnterPlanMode(loop)
        # EnterPlanMode 内部已 set_plan_mode(True) + 设 loop.mode="plan";同步本端 flag + 指示器。
        self._plan_mode = True
        self._set_plan_mode_indicators()
        await log.append_line(msg, kind="system")

    async def _hooks_cmd(self, log, arg: str) -> None:
        """/hooks / /hooks reload slash 命令入口。"""
        from argos_agent.hooks import get_config, reload_config, HooksConfigError
        if arg == "reload":
            try:
                cfg = reload_config()
                await log.append_line(
                    f"已重载 hooks 配置(共 {len(cfg.entries)} 个事件)。",
                    kind="system",
                )
            except HooksConfigError as e:
                await log.append_line(f"/hooks reload 失败(保留旧配置):{e}", kind="error")
            return
        # /hooks 无参 → 列当前配置
        cfg = get_config()
        if not cfg.entries:
            await log.append_line(
                "当前无 hooks 配置(空 ~/.argos/hooks.json 或未配置)。",
                kind="system",
            )
            return
        lines = [f"当前 hooks 配置({len(cfg.entries)} 个事件):"]
        for ev_name, entries in cfg.entries.items():
            lines.append(f" · {ev_name}:")
            for e in entries:
                matcher_str = f"matcher={e.matcher!r}" if e.matcher else "(全匹配)"
                lines.append(f"   - {matcher_str}")
                for h in e.hooks:
                    cmd_short = h.command[:60] + ("..." if len(h.command) > 60 else "")
                    lines.append(f"     · {cmd_short}  (timeout={h.timeout}ms)")
        await log.append_line("\n".join(lines), kind="system")

    async def _lsp_cmd(self, log, arg: str) -> None:
        """/lsp / /lsp reload slash 命令入口(spec 2026-06-06 §2.7)。"""
        from argos_agent import lsp as _lsp
        from argos_agent.lsp import get_config, reload_config, LspConfigError
        if arg == "reload":
            try:
                cfg = reload_config()
                await log.append_line(
                    f"已重载 LSP 配置(共 {len(cfg.servers)} 个 server)。",
                    kind="system",
                )
            except LspConfigError as e:
                await log.append_line(f"/lsp reload 失败(保留旧配置):{e}", kind="error")
            return
        # /lsp 无参 → 列当前 servers
        cfg = get_config()
        if not cfg.servers:
            await log.append_line(
                "当前无 LSP 配置(空 ~/.argos/lsp.json 或不可读 → 走 built-in 默认)。",
                kind="system",
            )
            return
        try:
            mgr = _lsp.get_manager()
            servers = mgr.list_servers()
        except Exception as e:  # noqa: BLE001
            await log.append_line(f"LSP manager 初始化失败:{e}", kind="error")
            return
        lines = [f"当前 LSP 配置({len(servers)} 个 server):"]
        for s in servers:
            ft = ",".join(s["filetypes"])
            disabled_tag = " (disabled)" if cfg.servers.get(s["name"], None) and cfg.servers[s["name"]].disabled else ""
            lines.append(
                f" · {s['name']:<12} status={s['status']:<11} "
                f"ft={ft:<20} cmd={s['command']}{disabled_tag}"
            )
            if s.get("diag_count", 0) > 0:
                lines.append(f"     diagnostics: {s['diag_count']} 条")
        await log.append_line("\n".join(lines), kind="system")

    async def _permissions_cmd(self, log, arg: str) -> None:
        """/permissions / /permissions reload slash 命令入口(spec 2026-06-06 §2.6)。

        无参 → 列当前配置摘要(default_level / per-tool / allow / deny / ask 计数 + 关键 matcher 预览)
        reload → 重读 ~/.argos/permissions.json,坏配置保旧 + 报错(同 hooks / lsp 行为)。"""
        from argos_agent.permissions import (
            get_config, reload_config, PermissionsConfigError,
        )
        if arg == "reload":
            try:
                cfg = reload_config()
                await log.append_line(
                    f"已重载 permissions 配置(allow {len(cfg.allow)} / deny {len(cfg.deny)} / "
                    f"ask {len(cfg.ask)} / per-tool {len(cfg.tools)} / "
                    f"default_level={cfg.default_level or '(沿用 gate.level)'})。",
                    kind="system",
                )
            except PermissionsConfigError as e:
                await log.append_line(
                    f"/permissions reload 失败(保留旧配置):{e}", kind="error",
                )
            return
        # /permissions 无参 → 列当前配置摘要
        try:
            cfg = get_config()
        except Exception as e:  # noqa: BLE001
            await log.append_line(f"读取 permissions 配置失败:{e}", kind="error")
            return
        lines = [
            "当前 permissions 配置:",
            f" · default_level: {cfg.default_level or '(沿用 gate.level)'}",
            f" · per-tool 覆盖: {len(cfg.tools)} 个" + (
                "  " + ", ".join(f"{t}={lv}" for t, lv in cfg.tools.items()) if cfg.tools else ""
            ),
            f" · allow rules: {len(cfg.allow)} 条",
        ]
        for e in list(cfg.allow)[:5]:
            lines.append(f"   · {e.tool}  matcher={e.matcher!r}")
        if len(cfg.allow) > 5:
            lines.append(f"   …(共 {len(cfg.allow)} 条,省略 {len(cfg.allow) - 5})")
        lines.append(f" · deny rules: {len(cfg.deny)} 条")
        for e in list(cfg.deny)[:5]:
            lines.append(f"   · {e.tool}  matcher={e.matcher!r}")
        lines.append(f" · ask rules: {len(cfg.ask)} 条")
        for e in list(cfg.ask)[:5]:
            lines.append(f"   · {e.tool}  matcher={e.matcher!r}")
        await log.append_line("\n".join(lines), kind="system")

    async def _show_tools(self, log) -> None:
        """/tools:列出 agent 可调用的全部工具(诚实:数量 = 真实可调用工具数)。"""
        from argos_agent import tools as _tools
        names = _tools.ALL_TOOL_NAMES
        groups = [
            ("文件", ["read_file", "write_file", "edit_file", "search_files"]),
            ("命令/验证/计划", ["run_command", "propose_verify", "update_plan"]),
            ("联网", ["web_search", "web_extract"]),
            ("计算机控制(浏览器)", [n for n in names if n.startswith("browser_")]),
            ("外部工具", ["mcp_call"]),
            ("LSP 语言服务器", [n for n in names if n.startswith("lsp_")]),
            ("编排(工作流)", ["propose_workflow"]),
        ]
        lines = [f"共 {len(names)} 个工具:"]
        for label, members in groups:
            present = [m for m in members if m in names]
            if present:
                lines.append(f" · {label}:{', '.join(present)}")
        await log.append_line("\n".join(lines), kind="system")

    async def _runs_cmd(self, log, arg: str) -> None:
        """/runs / /runs {id} resume / cancel — daemon 模式 run 列表与控制(spec §2.6 e)。

        无 daemon 时 → 报"未启用 daemon";有 daemon → 列 run + 代理 pause/resume/cancel。
        """
        if not self._with_daemon or not self._daemon_client or not self._daemon_session_id:
            await log.append_line(
                "未启用 daemon(--with-daemon flag);/runs 不可用。",
                kind="system",
            )
            return
        parts = arg.split(None, 1)
        if not parts:
            # /runs 无参 → 列所有 run
            try:
                runs = await self._daemon_client.list_runs(self._daemon_session_id)
            except Exception as e:  # noqa: BLE001
                await log.append_line(f"列 run 失败:{e}", kind="error")
                return
            if not runs:
                await log.append_line("无 run。", kind="system")
                return
            import time as _time
            lines = ["Run 列表:"]
            for r in runs:
                age = int(_time.time() - r.get("created_at", 0))
                lines.append(
                    f" · {r['run_id']}  {r['state']:<10}  {r['goal'][:40]}  ({age}s ago)"
                )
            lines.append("/runs {id} resume|cancel — 控制")
            await log.append_line("\n".join(lines), kind="system")
            return
        # /runs {id} [resume|cancel]
        run_id = parts[0]
        action = parts[1].strip() if len(parts) > 1 else "info"
        if action == "resume":
            try:
                await self._daemon_client.resume(self._daemon_session_id, run_id)
                await log.append_line(f"已请求 resume {run_id}。", kind="system")
            except Exception as e:  # noqa: BLE001
                await log.append_line(f"resume 失败:{e}", kind="error")
        elif action == "cancel":
            try:
                await self._daemon_client.cancel(self._daemon_session_id, run_id)
                await log.append_line(f"已请求 cancel {run_id}。", kind="system")
            except Exception as e:  # noqa: BLE001
                await log.append_line(f"cancel 失败:{e}", kind="error")
        else:
            try:
                info = await self._daemon_client.get_run(self._daemon_session_id, run_id)
                await log.append_line(
                    f"{run_id}: state={info.get('state')}  events={info.get('events_count')}",
                    kind="system",
                )
            except Exception as e:  # noqa: BLE001
                await log.append_line(f"查 run 失败:{e}", kind="error")

    async def _skill_cmd(self, log, skill_name: str, arg: str) -> None:
        """/verify / /security-review / /simplify 统一入口(spec §2.6 / §2.7)。

        解析 path → run_skill → chat 追加 summary + findings 表格。
        """
        from pathlib import Path as _P
        from argos_agent.skills_runtime.analysis import AnalysisSkillContext
        from argos_agent.skills_runtime import run_skill, register_builtin_skills

        # 首次调用注册 builtin(幂等)
        register_builtin_skills()
        path = arg.strip() or None
        workspace = _P.cwd()
        ctx = AnalysisSkillContext(
            workspace=workspace, approval_level="auto", run_id=f"slash-{skill_name}",
        )
        try:
            result = await run_skill(skill_name, {"path": path}, ctx)
        except Exception as e:  # noqa: BLE001
            await log.append_line(f"/{skill_name} 失败:{e}", kind="error")
            return
        await log.append_line(result.summary, kind="info")
        if result.findings:
            await log.append_line("", kind="info")
            for f in result.findings:
                loc = f"{f.file}:{f.line}" if f.file and f.line else (f.file or "(workspace)")
                await log.append_line(
                    f"  F-{f.severity} · {f.category} · {loc} · {f.message}",
                    kind="error" if f.severity == "error" else "info",
                )
                if f.suggestion:
                    await log.append_line(f"    fix: {f.suggestion}", kind="info")

    async def _remember_cmd(self, log, text: str) -> None:
        """/remember <text>:追加一条用户记忆(scope 自动判 user/project)。"""
        if not text.strip():
            await log.append_line("用法:/remember <要记住的内容>", kind="error")
            return
        from argos_agent.memory import auto as _mem
        pid = _mem.project_id_for()
        e = _mem.remember(text, project_id=pid)
        if e is None:
            await log.append_line("(已是最新 — 24h 内重复 / 空内容 / 解析失败,跳过)",
                                 kind="info")
            return
        await log.append_line(
            f"已记住 ({e.scope}): {e.value} (id={e.id}, conf={e.confidence:.2f})",
            kind="done",
        )

    async def _forget_cmd(self, log, query: str) -> None:
        """/forget <id|key|text>:软删(confidence=0,后台 prune 真删)。"""
        if not query.strip():
            await log.append_line("用法:/forget <id 或 key 或 文本>", kind="error")
            return
        from argos_agent.memory import auto as _mem
        pid = _mem.project_id_for()
        sid = self._session_id
        out = _mem.forget(query, project_id=pid, session_id=sid)
        if not out:
            await log.append_line(f"未找到匹配 '{query}' 的记忆。", kind="info")
            return
        await log.append_line(f"已软删 {len(out)} 条:", kind="done")
        for e in out:
            await log.append_line(f"  - {e.id} ({e.scope}) {e.key} = {e.value[:60]}",
                                 kind="info")

    async def _memory_cmd(self, log) -> None:
        """/memory:列出 4 tier 摘要(只读)。"""
        from argos_agent.memory import auto as _mem
        pid = _mem.project_id_for()
        sid = self._session_id
        text = _mem.view_all(project_id=pid, session_id=sid)
        await log.append_line(text, kind="system")

    async def _show_skills(self, log) -> None:
        """/skills:列出可用技能(按任务自动召回进系统提示)。诚实:读真实 skill 库。"""
        try:
            from argos_agent import skills as _skills
            all_skills = _skills.load_all()
        except Exception as e:  # noqa: BLE001
            await log.append_line(f"读取技能失败:{e}", kind="error")
            return
        if not all_skills:
            await log.append_line("当前无可用技能(~/.argos/skills/ 为空,可导入)。", kind="system")
            return
        lines = [f"可用技能 {len(all_skills)} 个(运行任务时按相关性自动召回):"]
        for s in all_skills:
            mark = "" if s.enabled else "(已禁用)"
            lines.append(f" · {s.name}{mark} — {s.description}")
        await log.append_line("\n".join(lines), kind="system")

    async def _show_mcp(self, log) -> None:
        """/mcp:列出 ~/.argos/mcp.json 配置的 MCP server + 已连接工具(诚实:不谎报连接态)。"""
        try:
            from argos_agent import mcp_native
            mgr = mcp_native.get_manager()
            tools = mgr.list_tools()   # 阻塞确保连接(用户主动查时可接受短暂等待)
        except Exception as e:  # noqa: BLE001
            await log.append_line(f"MCP 查询失败:{e}", kind="error")
            return
        if not tools:
            await log.append_line(
                "未配置 MCP,或配置的 server 未连上 / 无工具。\n"
                "在 ~/.argos/mcp.json 配置 stdio server 即可扩展工具(默认零预配)。",
                kind="system")
            return
        by_server: dict[str, list] = {}
        for t in tools:
            by_server.setdefault(t.server, []).append(t)
        lines = [f"已连接 MCP 工具 {len(tools)} 个,经 mcp_call(server, tool, arguments) 调用:"]
        for server, ts in by_server.items():
            lines.append(f" · {server}:{', '.join(t.name for t in ts)}")
        await log.append_line("\n".join(lines), kind="system")

    async def _resume_recent(self, log) -> None:
        """/resume:把当前会话切到【最近一次历史会话】,使后续任务带回它的上下文(agent 记得上次)。
        每次启动默认全新 session(故重开窗口不自动记得);想续上一次显式 /resume 即可。
        实现:从 store 取最近会话(排除本次启动的空 session),切 self._session_id —— loop 跨轮据它
        get_messages 还原历史。不做可视回放(屏幕仍空),但 agent 已带回上文。"""
        loop = self._loop_factory()
        store = getattr(loop, "store", None)
        if store is None or not hasattr(store, "list_sessions"):
            await log.append_line("/resume 不可用(当前无持久化会话)。", kind="error")
            return
        sessions = [s for s in store.list_sessions(limit=10) if s.session_id != self._session_id]
        if not sessions:
            await log.append_line("没有可恢复的历史会话。", kind="system")
            return
        prev = sessions[0]   # 最近一次(list_sessions 按 started_at DESC)
        self._session_id = prev.session_id
        msgs = store.get_messages(prev.session_id) if hasattr(store, "get_messages") else []
        title = (prev.title or prev.session_id[:8]).strip() or prev.session_id[:8]
        await log.append_line(
            f"已恢复会话「{title}」,带回 {len(msgs)} 条历史 —— 继续输入即接上文。", kind="done")

    # ── 一轮 run:EventBus + loop + Worker 消费 ────────────────────────────
    async def start_run(self, goal: str) -> None:
        if self._run_active:
            return
        self._run_active = True
        # 拍本轮 run 的 workspace 快照(供 /undo 还原)。
        # 命名 = {session_id}-app{run_seq}.tar,与 loop 内部 {session_id}-{ms}.tar 不冲突
        # (两个快照并存,App 优先用自己拍的这个,loop 那个是 loop 自身的副本能继续 restore)。
        # 拍快照失败不阻塞 run —— _snapshot 留 None,/undo 报"无可撤销"。
        self._run_seq += 1
        self._snapshot = None
        try:
            tar_path = SNAPSHOT_ROOT / f"{self._session_id}-app{self._run_seq}.tar"
            self._snapshot = RunSnapshot.take(self._workspace, tar_path)
        except Exception:  # noqa: BLE001
            pass
        self._glow_start()
        for sp in self.query(StartupSplash):
            await sp.remove()
        self._step_blocks = {}  # 每轮独立,杜绝跨轮 step 串台。
        self.query_one("#activity", ActivityPanel).reset_run()  # 每轮起手清活动栏(进度/工具/回执)。
        # UserPromptSubmit hook fire(spec §2.5:TUI 端触发,不在 loop 内)
        try:
            from argos_agent import hooks as _hooks
            from argos_agent.hooks.payload import build_user_prompt_payload
            from argos_agent.hooks.events import HookFired as _HookFired
            ups_payload = build_user_prompt_payload(
                session_id=self._session_id, cwd=str(self._workspace), goal=goal,
            )
            ups_result = await _hooks.fire(
                "UserPromptSubmit", ups_payload,
                cwd=self._workspace, session_id=self._session_id,
            )
            for h in ups_result.per_hook:
                # UserPromptSubmit 投 HookFired 走 EventBus 让活动栏渲染
                self.run_worker(self._apply_event(_HookFired(
                    event_name="UserPromptSubmit", command=h.command,
                    success=h.success, returncode=h.returncode,
                    elapsed_ms=h.elapsed_ms, timed_out=h.timed_out,
                    not_found=h.not_found, stop_reason=h.stop_reason,
                    error=h.error,
                )), exclusive=False)
        except Exception:  # noqa: BLE001 — hook 失败不阻断 start_run
            pass
        bus = EventBus()
        loop = self._loop_factory()
        # Plan mode spec §2.5:loop 投 PlanRendered 事件时 _apply_event 回调里要调
        # ExitPlanMode(loop, ...) + set _plan_decision_event 唤醒 loop 的 await。把本轮
        # loop 引用挂到 self 上,事件回调闭包外也能拿到(每轮 run 起始重设,无跨轮泄漏)。
        self._current_loop = loop
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

        self._interrupted = False
        self._produce_worker = self.run_worker(_produce(), exclusive=False)
        try:
            async for ev in bus:
                await self._apply_event(ev)
        finally:
            # 兜底落定:append_token 把流式尾段滞留 current 气泡,只在 PhaseChange/append_line 落定。
            # 一轮结束时强制落定残余,杜绝"模型最后一句没换行 → 永远不计入 rendered_text"的隐形吞字。
            log.finalize_response()
            self._run_active = False
            self._produce_worker = None
            self._glow_stop()
            if self._interrupted:
                # Esc 打断收尾:落一行明确告知(诚实——已停在当前步,不假装完成)。
                await log.append_line("⎋ 已打断当前任务。", kind="system")
                self._interrupted = False

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
                self._glow_base = glow.phase_color(ev.phase)  # 呼吸基色随阶段切换
                self._set_border(self._glow_base)
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
            # 上下文占用%用【实际运行模型】的窗口当分母(active_tier),不能用模块级默认值——
            # 否则 active 是小窗口模型(如 Ollama 8192)时会拿 192000 当分母,谎报上下文压力。
            window = self._display_tier().context_window
            ap.on_context(used=ev.context_used, window=window)
        elif isinstance(ev, PlanUpdate):
            # 真 TODO 拆解 → 活动栏"任务进度"区改渲染子任务进度(Task 12)。
            ap.on_plan(ev.todos)
        elif isinstance(ev, WorkflowProposed):
            await self._handle_workflow_proposed(ev)
        elif isinstance(ev, WorkflowProgress):
            # 子 agent 阶段流转 → 刷新进度树那一行。面板不存在(异常/乱序)则忽略,不崩。
            if self._workflow_panel is not None:
                self._workflow_panel.update_progress(ev.agent_id, ev.phase, ev.note)
        elif isinstance(ev, WorkflowDone):
            if self._workflow_panel is not None:
                self._workflow_panel.finish(ev.synthesis, ev.notes)
            # 汇总落对话流(synthesis 可能含 `[...]`,append_line 走 SystemLine 已 markup=False,安全)。
            await log.append_line(
                f"⚙ 工作流「{ev.name}」完成:{ev.synthesis}", kind="done")
        elif isinstance(ev, ToolReceipt):
            # 回执进活动栏面板的"回执"区 + 工具计数,不再进 transcript(Task 10)。
            ap.on_receipt(ev.receipt.action)
        elif isinstance(ev, ApprovalRequest):
            await self._handle_approval(ev)
        elif isinstance(ev, PlanRendered):
            # Plan mode spec §2.5:loop 投 PlanRendered → TUI 推 PlanModal + 回调里把用户决策
            # 写回 loop._plan_decision + set event 唤醒 loop 的 await(见 _handle_plan_rendered)。
            await self._handle_plan_rendered(ev)
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

    def action_interrupt(self) -> None:
        """Esc:打断当前 run(daemon 模式 = step-boundary pause,legacy = 整 run kill)。

        daemon 模式行为(spec §2.7):
          · 单 Esc → POST /runs/{id}/pause;worker 在下个 step 边界 await 暂停
          · 双 Esc(1.5s 内) → POST /runs/{id}/cancel;worker 协程 cancel
          · 取消生产 worker → 其 finally 关闭 bus → 消费循环 start_run 自然收尾
            (落 '已打断' 行、解锁 run_active、停呼吸光)。

        legacy 模式(无 daemon):直接 cancel 生产 worker(对齐 Claude Code 旧行为)。

        idle(无 run)时无副作用。
        诚实边界:模型推理/网络等 await 点能即时停;卡在同步 exec_code(命令/浏览器)需等其返回。"""
        import time
        # Esc 双用:slash 菜单开着时先收菜单(不打断);否则才打断当前 run。
        menu = self.query_one("#slash-menu", SlashMenu)
        if menu.display:
            menu.hide()
            return
        if not self._run_active or self._produce_worker is None:
            return
        now = time.time()
        if self._with_daemon and self._daemon_client is not None and self._daemon_session_id:
            # daemon 模式:2 阶段契约 — 双 Esc = cancel
            if (now - self._last_esc_time) < 1.5:
                # 双 Esc → cancel
                self._interrupted = True
                try:
                    self._daemon_client.cancel(self._daemon_session_id, self._daemon_run_id)
                except Exception:  # noqa: BLE001
                    pass
                try:
                    self._produce_worker.cancel()
                except Exception:  # noqa: BLE001
                    pass
                self._last_esc_time = 0.0
                return
            # 单 Esc → pause(step boundary)
            self._last_esc_time = now
            try:
                # 协程里跑 async;这里 fire-and-forget
                self.run_worker(self._daemon_pause(), exclusive=False)
            except Exception:  # noqa: BLE001
                pass
            return
        # legacy 模式:整 run cancel
        self._interrupted = True
        self._last_esc_time = 0.0
        try:
            self._produce_worker.cancel()
        except Exception:  # noqa: BLE001 — worker 可能已自然结束,取消失败无碍
            pass

    async def _daemon_pause(self) -> None:
        """daemon 模式 Esc → POST /pause(2 阶段:202 + 后续 SSE state_change 事件)。"""
        if not self._daemon_client or not self._daemon_session_id or not self._daemon_run_id:
            return
        try:
            await self._daemon_client.pause(self._daemon_session_id, self._daemon_run_id)
        except Exception as e:  # noqa: BLE001
            log = __import__("logging").getLogger(__name__)
            log.warning("daemon pause failed: %s", e)

    def action_background(self) -> None:
        """Ctrl+B:把当前 run 后台化(running → suspended;checkpoint 落盘)。

        spec §2.6 b 段:daemon 模式才生效;legacy 模式无副作用(诚实:不做假装操作)。
        后台化后 transcript 显一行 'Run <id> suspended' + 用户可立刻开新目标。
        """
        if not self._with_daemon or not self._daemon_client or not self._daemon_session_id:
            # legacy 模式 → no-op(无副作用)
            return
        if not self._run_active or not self._daemon_run_id:
            return
        # 后台化:把 produce_worker cancel(loop 真转 paused/suspended)
        # 实际状态转换由 daemon 端 worker 协程 mark_suspended 完成
        # 简化:这里直接 cancel + 期望 daemon 端 catch CancelledError + mark_suspended
        try:
            self._produce_worker.cancel()
        except Exception:  # noqa: BLE001
            pass
        # 落一行告知用户
        try:
            log_widget = self.query_one("#transcript", Transcript)
            self.run_worker(
                log_widget.append_line(
                    f"⏸ Run {self._daemon_run_id} 后台化(suspended)。可 /resume {self._daemon_run_id} 续。",
                    kind="system",
                ),
                exclusive=False,
            )
        except Exception:  # noqa: BLE001
            pass

    async def _handle_workflow_proposed(self, ev: WorkflowProposed) -> None:
        """工作流提议:① mount 进度树面板(存引用,后续 Progress/Done 据它刷新);
        ② 非 AUTO 档弹审批模态显 preview,回调 gate.respond(call_id, decision) 放行 loop 的 await。
        AUTO 档下 loop 侧 gate.request 已自动放行、不真等 respond,故只 mount 面板、不弹模态
        (弹了也无 respond 对象,且 always 会多余)。"""
        log = self.query_one("#transcript", Transcript)
        panel = WorkflowPanel(name=ev.name)
        self._workflow_panel = panel
        await log.mount_block(panel)
        if self.gate.level is ApprovalLevel.AUTO:
            return  # loop 侧已自放行,不再弹模态

        call_id = ev.call_id

        def _cb(decision: str | None) -> None:
            d = decision or "deny"
            self.gate.respond(call_id, d)  # type: ignore[arg-type]
            self.run_worker(
                log.append_line(f"工作流审批:{ev.name} → {d}"),
                exclusive=False,
            )

        await self.push_screen(WorkflowApprovalModal(ev.preview), _cb)

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

    async def _handle_plan_rendered(self, ev: "PlanRendered") -> None:
        """Plan mode spec §2.5:PlanRendered 事件 → 推 PlanModal(4 选项审批)→ 决策回传 loop。

        流程:
          1. AUTO 档(YOLO)直接按 approve_start 落决策 + 唤醒 loop(不弹窗)
          2. CONFIRM/PROPOSE 档 → push_screen(PlanModal) 等用户选 1/2/3/4
          3. modal 回调里 ExitPlanMode(loop, action, feedback);唤醒 loop 的 await 由
             ExitPlanMode 自己负责(校验通过 → 自动 set event),TUI 不再手动 set。
             (历史教训:之前 TUI 在 ExitPlanMode 失败后仍 set event,导致 Refine 校验失败
             时被静默兜底成 Approve;现在 ExitPlanMode 原子完成,失败时不 set,无此洞。)
        """
        from argos_agent.core.plan_mode import ExitPlanMode
        loop = self._current_loop
        if loop is None:
            return  # run 已结束(并发事件兜底)

        if self.gate.level is ApprovalLevel.AUTO:
            # YOLO:不弹窗,直接 approve_start 走完(spec §2.5 等价于按 1)
            ExitPlanMode(loop, "approve_start")
            return

        def _cb(decision: PlanDecision | None) -> None:
            if decision is None:
                return  # Esc 退屏:不写决策,让 loop 继续挂(诚实:用户没拍就不放)
            ExitPlanMode(loop, decision.action, decision.feedback)
            # ExitPlanMode 内部已 set event(校验失败时不动,避免 Refine→Approve 兜底)。
            # 落一行告知用户(append_line 是 async,回调是同步的 → 包成 worker)
            self.run_worker(
                self.query_one("#transcript", Transcript).append_line(
                    f"Plan 决策:{decision.action}", kind="system"
                ),
                exclusive=False,
            )

        await self.push_screen(PlanModal(plan_md=ev.plan_md), _cb)
