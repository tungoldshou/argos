"""Argos TUI 主屏(TUI v2 spec 2026-06-10)。

布局:TopBar(自绘 1 行,含模式徽标) + Transcript(主对话) + ActivityPanel(右栏智能切)
+ PromptArea + StatusBar(含键提示)。无 stock Header/Footer。
事件桥:start_run 起一个 EventBus + 注入的 loop,Worker async-for 消费 Event 并更新 widget(契约 §1/§3)。
slash:输入以 / 开头走 commands.parse_slash 分发;否则当 goal 起一轮 run。
审批:loop 投 ApprovalRequest → Transcript 流内 mount InlineChoice → 回调里 gate.respond(契约 §6.3);
同屏最多一个活动 InlineChoice,其余 FIFO 排队。
"""
from __future__ import annotations

import uuid
from collections import deque
from collections.abc import Callable
from pathlib import Path

from textual.app import App, ComposeResult
from textual.containers import Horizontal

from argos import config
from argos.approval import ApprovalGate, ApprovalLevel
from argos.core.snapshot import SNAPSHOT_ROOT, RunSnapshot
from argos.tui.commands import SlashCommand, match_commands, parse_slash
from argos.tui.events import (
    ApprovalRequest,
    ApprovalResponse,
    CodeAction,
    CodeResult,
    CompactedEvent,
    ComputerActionEvent,  # ← P6a §10 computer use
    DreamProgressEvent,   # ← T10 Dream 夜间整合进度
    DreamReportEvent,     # ← T10 Dream 夜间整合结果汇总
    CostUpdate,
    Error,
    Escalation,
    Event,
    EventBus,
    FileDiff,
    MemoryRecallEvent,
    PhaseChange,
    PlanDecisionRequest,
    PlanRendered,
    PlanUpdate,
    ProactiveSuggestionEvent,  # ← P5b §9 自治面
    PrunedEvent,
    TokenDelta,
    ToolReceipt,
    VerifyVerdict,
    WorkflowDone,
    WorkflowProgress,
    WorkflowProposed,
)
from argos.tui.fakeloop import FakeLoop
from argos.tui.theme import ARGOS_NIGHT
from argos.tui.widgets.activity_panel import ActivityPanel
from argos.tui.widgets.code_action import CodeActionBlock
from argos.tui.widgets.diff_view import DiffView
from argos.tui.widgets.dream_report import DreamReportCard
from argos.tui.widgets.hard_confirm_card import HardConfirmCard
from argos.tui.widgets.inline_choice import InlineChoice, format_approval_title
from argos.tui.widgets.ledger_table import LedgerTable
from argos.tui.widgets.orders_panel import OrdersPanel
from argos.tui.widgets.orders_panel import ConductorSuggestionChoice
from argos.tui.widgets.routing_table import RoutingTable
from argos.tui.widgets.trust_dial import TrustDial
from argos.tui.widgets.prompt import PromptArea, SlashMenu
from argos.tui.widgets.splash import StartupSplash
from argos.tui.widgets.status_bar import StatusBar
from argos.tui.widgets.tab_strip import TabActivated, TabStrip
from argos.tui.widgets.thinking import ThinkingIndicator
from argos.tui.widgets.top_bar import TopBar
from argos.tui.widgets.transcript import Transcript
from argos.tui.widgets.verdict_badge import VerdictBadge
from argos.input.recorder import Recorder, RecorderError
from argos.input.stt import LocalWhisper, make_transcriber, SttError
from argos.input.stt_config import load_stt_config
from argos.input.clipboard_image import read_clipboard_image, ClipboardError
from argos.tui.widgets.workflow_panel import WorkflowPanel

_BASE_SUBTITLE = "百眼智能体"


def _app_version() -> str:
    """TopBar 显示用版本(单一来源 argos.__version__ ← pyproject/VERSION,与 splash 同口径)。
    不能用 version("argos") —— 分发名是 "argos-agent",查 "argos" 必 PackageNotFoundError 回退
    "0.x"(2026-06-16 真机:顶栏显示 v0.x 的根因)。argos.__version__ 已做 argos-agent + VERSION 兜底。"""
    try:
        from argos import __version__
        return __version__
    except Exception:  # noqa: BLE001
        return "0.x"


class ArgosApp(App):
    TITLE = "Argos"

    # 布局 CSS(spec §5 mockup:主对话区 + 右侧活动栏)。没有它时 Horizontal 退回 Textual 默认:
    # 空 Transcript 收缩到 width=1、侧栏撑满整宽 → 对话内容渲染进 1 列宽的 transcript,
    # 用户看到的永远是空屏(事件其实都写进去了,只是不可见)。这里显式分配:transcript 占满
    # 剩余宽度(1fr);ActivityPanel 的固定窄栏宽度由其 DEFAULT_CSS 承担。
    #
    # 黑曜石纵深(spec §5):Screen 底 $abyss(井底,最外),主流 Transcript $stream(亮一档),
    # 右栏/输入 $well(暗一档)——分栏靠背景色差,不画竖线(§4.8 裁决)。idle 边框走 $hairline-lit
    # (run 期间由 _glow_start/_set_border 接管成阶段呼吸色,收尾回 glow.IDLE_BORDER)。
    CSS = """
    Screen { border: round $hairline-lit; background: $abyss; }
    #transcript {
        width: 1fr;
        height: 1fr;
        background: $stream;
    }
    #activity {
        height: 1fr;
        display: block;
    }
    #prompt { border: none; border-top: solid $hairline; background: $well; }
    ArgosApp.-narrow #activity { display: none; }
    """

    # 窄屏(<90 列)折叠右侧活动栏,把整宽让给对话(Task 14:响应式)。
    HORIZONTAL_BREAKPOINTS = [(0, "-narrow"), (90, "-wide")]

    # 启动/换屏后由 Textual 自动把焦点放到输入框(声明式,框架在正确时机执行)——
    # 否则默认聚焦第一个可聚焦 widget。Transcript 已 can_focus=False 不抢焦点,
    # 这里仍显式声明作双保险。与 on_mount 的手动 focus 一致。
    AUTO_FOCUS = "#prompt"

    # Esc / Ctrl+C 打断当前任务(对齐 Claude Code / all major agent CLIs):
    #   · ctrl+c → interrupt(打断当前 run;idle 时第一次无副作用,第二次 1.5s 内退出)
    #   · ctrl+d → quit(确定性退出,无论是否有 run)
    #   · escape → interrupt(同 ctrl+c;收起菜单 / 打断二合一)
    # 这与 Claude Code / shell 约定一致:Ctrl+C 是"打断/中断",Ctrl+D 是"退出/EOF"。
    # `Ctrl+B` 后台化(daemon 模式):把当前 run 推到 daemon → state=suspended(可跨 session 续)。
    BINDINGS = [
        ("ctrl+c", "ctrl_c", "打断/退出"),       # 打断 run;双击退出(同 Claude Code)
        ("ctrl+d", "quit", "退出"),               # 确定性退出(同 shell EOF)
        ("escape", "interrupt", "打断"),
        ("ctrl+b", "background", "后台"),
        ("ctrl+o", "cycle_panel", "右栏视图"),    # TUI v2:智能切手动 pin/循环
        ("ctrl+v", "paste_image", "贴图"),        # 读剪贴板图片 → [图片 #N] chip
        # #5b T7:tab 切换(放在 Ctrl+1..5 子绑定,tab_strip widget 自己处理)
    ]

    def __init__(
        self, *, loop_factory: Callable[[], object] | None = None, demo: bool = True,
        gate: ApprovalGate | None = None,
        workspace: Path | str | None = None,
    ) -> None:
        super().__init__()
        # 真实 workspace(入口解析:--project 或 cwd 默认);None = 旧默认 ~/.argos/workspace。
        # 必须与 build_components 用的同一路径,否则 daemon create_run 会把 run 落到错误目录
        # (实测 bug:在 ~/argos-field-test 启动,agent 却跑在默认工作区整理不到任何文件)。
        self._workspace_override: Path | None = (
            Path(workspace).expanduser().resolve() if workspace else None
        )
        # 主题必须在 compose(DOM 构建)之前注册并激活——Textual 8.x 的事件顺序是
        # Compose(line 3432) → Load(line 3477) → Mount；widget DEFAULT_CSS 在 compose
        # 时解析，若此时 argos-night 未注册，$abyss/$ink-faint 等 v3 token 将
        # UnresolvedVariableError 导致 compose 崩溃、on_mount 永远跑不到。
        self.register_theme(ARGOS_NIGHT)
        self.theme = "argos-night"
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
        # 入口传入的真实 workspace 优先(与 build_components 同源);否则旧默认。
        self._workspace: Path = self._workspace_override or (Path.home() / ".argos" / "workspace")
        self._run_seq: int = 0
        self._snapshot: "RunSnapshot | None" = None
        # ── Daemon 模式状态(v6 P3b §2)────────────────────────────────
        # _kernel_mode 枚举:
        #   ""        = 未初始化(DEMO / on_mount 前)
        #   "inline"  = 单进程直跑(daemon 不可达,inline fallback)
        #   "argosd"  = 走 daemon 协议(argosd 进程;事件经 DaemonEventSource)
        # 诚实铁律:只改写真实状态,绝不把 inline 标注为 argosd。
        self._kernel_mode: str = ""
        # _with_daemon:True = 已通过模式探测确认 daemon 可用,走协议路径。
        # 历史遗留字段保留(命令/条件判断大量依赖),P3b 中由 _kernel_mode 覆盖语义。
        self._with_daemon: bool = False
        self._daemon_client = None     # type: ignore[var-annotated]
        self._daemon_session_id: str | None = None
        self._daemon_run_id: str | None = None   # 当前 run 在 daemon 里的 run_id
        self._last_esc_time: float = 0.0          # 双 Esc 检测(1.5s 内第二次 = cancel)
        self._last_ctrl_c_time: float = 0.0       # 双 Ctrl+C 检测(1.5s 内第二次 = quit)
        # 输入历史环形缓冲(#20):存最近 N 条 goal/slash 提交,↑/↓ 回填输入框
        self._input_history: list[str] = []
        self._input_history_max: int = 50
        # TUI v2 行内审批队列:同屏最多一个活动 InlineChoice,其余 FIFO 排队
        #(并发 ApprovalRequest 不互踩;前一个决策落定后再 mount 下一个)。
        self._choice_active = False
        self._choice_queue: deque[Callable[[], InlineChoice]] = deque()
        # v6 P3b §4:当前 plan 决策的 call_id(PlanDecisionRequest 事件到达时设置)。
        # _handle_plan_rendered 据此路由 respond_plan_decision / POST plan_decision。
        self._current_plan_call_id: str | None = None
        # 语音输入状态(Task 5 voice input):录音/转写/注入循环。
        self._voice_recording: bool = False
        self._voice_recorder = None
        self._voice_transcriber = None
        self._stt_warmed = False   # 首次本地转写可能要懒下载模型权重 → 首次用更诚实的标签(排查 #4)
        self.sub_title = self._compose_subtitle()

    @staticmethod
    def _display_tier():
        """当前 active 模型的 tier(活动栏/启动画面/上下文窗口显示用);
        配置异常或无 config 时回退 DEFAULT_TIER,绝不崩 UI。无 worker/premium 档位。"""
        from argos import config
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

    def _resolve_trust_level(self):
        """从 gate 反查当前 Trust 档位(单一真源,与 TopBar Trust 徽标 + /trust 共用)。

        set_trust_level 存的原始档位优先(反向映射有损:L2 会被误报成 L1——不许对用户失真);
        其次按 gate.level 反查;_ask_readonly=True 精确判 L0;兜底 L1。
        """
        from argos.permissions.trust_dial import TrustLevel
        _map = {
            ApprovalLevel.CONFIRM:      TrustLevel.L1_DANGEROUS_ONLY,
            ApprovalLevel.ACCEPT_EDITS: TrustLevel.L3_SESSION_TRUSTED,
            ApprovalLevel.AUTO:         TrustLevel.L4_AUTONOMOUS,
            ApprovalLevel.OBSERVE:      TrustLevel.L0_EVERY_STEP,
            ApprovalLevel.PROPOSE:      TrustLevel.L0_EVERY_STEP,  # PROPOSE 退化 L0
        }
        current = _map.get(self.gate.level, TrustLevel.L1_DANGEROUS_ONLY)
        if getattr(self.gate, "_ask_readonly", False):
            current = TrustLevel.L0_EVERY_STEP
        stored = getattr(self.gate, "_trust_level", None)
        if isinstance(stored, TrustLevel):
            current = stored
        return current

    def _refresh_topbar(self) -> None:
        """状态变化(plan/YOLO/DEMO/key/trust)→ TopBar 徽标对齐(诚实:全部来自真实状态)。"""
        try:
            tl = self._resolve_trust_level()
            self.query_one("#top-bar", TopBar).set_state(
                plan_mode=self._plan_mode, yolo=self._yolo,
                demo=self._demo, has_key=bool(config.active_key()),
                trust_level=int(tl), trust_label=tl.label_human,
            )
        except Exception:  # noqa: BLE001 — 未 mount(测试直构)时静默,数据已在字段里
            pass

    async def action_paste_image(self) -> None:
        """Ctrl+V:读系统剪贴板图片 → 在输入框插入 [图片 #N] chip。
        诚实:无图 / 无工具 / 平台不支持 → transcript 落明确原因,不崩、不伪绿。"""
        try:
            att = read_clipboard_image()
        except ClipboardError as e:
            self.run_worker(
                self.query_one("#transcript", Transcript).append_line(
                    f"⚠︎ 贴图失败:{e}", kind="error",
                ),
                exclusive=False,
            )
            return
        try:
            prompt = self.query_one("#prompt", PromptArea)
        except Exception:  # noqa: BLE001 — 无输入框(不该发生)
            return
        token = prompt.register_image(att)
        prompt.insert(token)

    def action_cycle_panel(self) -> None:
        """Ctrl+O:右栏视图循环(auto → idle → plan → act → verify → auto)。"""
        try:
            self.query_one("#activity", ActivityPanel).cycle_view()
        except Exception:  # noqa: BLE001 — 窄屏隐藏/测试场景:无副作用
            pass

    def compose(self) -> ComposeResult:
        # TUI v2:自绘 TopBar 替代 stock Header(键提示并入 StatusBar,无 Footer)。
        tier = self._display_tier()
        yield TopBar(version=_app_version(), model_label=tier.model, id="top-bar")
        # #5b 多 run tabs:顶部 tab 条(隐藏当 daemon 未启用时)
        yield TabStrip(id="tab-strip")
        with Horizontal():
            yield Transcript(id="transcript")
            yield ActivityPanel(id="activity", model_label=tier.model, tier=tier.name)
        yield StatusBar(id="status-bar")
        # slash 菜单(默认隐藏)叠在输入框上方:打 / 时列出命令;PromptArea 是多行输入(Enter 提交)。
        yield SlashMenu(id="slash-menu")
        yield PromptArea(placeholder="› 输入目标,或 / 开始命令", id="prompt")

    def on_mount(self) -> None:
        """启动即把焦点放到输入框。否则 Textual 默认聚焦第一个可聚焦 widget。Transcript 已
        can_focus=False(不抢焦点),但仍显式 focus 输入框作双保险,杜绝任何可聚焦兄弟
        排在 Input 之前抢走按键、用户在输入框打不了字(汉字/ASCII 都进不去)。与 AUTO_FOCUS 双保险。"""
        self._refresh_topbar()
        self.query_one("#prompt", PromptArea).focus()
        tier = self._display_tier()
        # has_key 必须真查 config.active_key(),不能只信 demo 开关(2026-06-09 修复假阳:
        # demo=False + 没配 key 此前显 LIVE 撒了谎,跑起来 401)
        self.query_one("#transcript", Transcript).mount(
            StartupSplash(
                model_label=tier.model, tier=tier.name,
                live=not self._demo, has_key=bool(config.active_key()),
            )
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
            from argos.hooks import reload_config
            reload_config()
        except Exception as e:  # noqa: BLE001 — 坏配置 banner,run 正常起
            for sp in self.query(StartupSplash):
                sp.set_bad_config(str(e))
        try:
            from argos.lsp import reload_config as _lsp_reload_config
            _lsp_reload_config()
        except Exception as e:  # noqa: BLE001 — LSP 坏配置 banner,run 正常起
            for sp in self.query(StartupSplash):
                sp.set_bad_config(f"LSP {e}")
        # Smart approval(spec 2026-06-06 §2.6):启动时 reload + 接 TUI ActivityPanel 决策监听 +
        # 把 workspace 注入 gate 让 evaluator 跑 system path / workspace 边界 check。
        try:
            from argos.permissions import reload_config as _perm_reload_config
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
        # gate「需交互审批」带外回调:inline 模式下,broker-gated 工具的审批在 exec_code(已挪进
        # to_thread)中经桥发起,此刻 loop 事件生成器阻塞在 await、yield 不出 ApprovalRequest → 旧路径
        # TUI 永远收不到、不 mount 审批卡 → 工具干等到超时(2026-06-18 真机:run_command/web_search
        # 全卡 30s)。此回调让 gate 在 ask 时直接把卡送到 TUI。daemon 路径不靠它(走 SSE)。
        try:
            self.gate.set_ask_listener(self._on_gate_ask)
        except Exception:  # noqa: BLE001
            pass
        # workspace 注入(诚实:_workspace 是 host 启动时计算好的工作目录;evaluator 据此跑边界)
        try:
            self.gate.set_workspace(str(self._workspace))
        except Exception:  # noqa: BLE001
            pass
        # v6 P3b §2:daemon 模式探测 + 拉起(后台 worker,探测期间 TUI 正常可用)。
        # 诚实:探测结果决定 _kernel_mode 标注,绝不在确认前假装已连通。
        if not self._demo:
            self.run_worker(self._setup_daemon_mode(), exclusive=False)

    async def _setup_daemon_mode(self) -> None:
        """v6 P3b §2:启动时探测 daemon socket → 尝试拉起 → 确定模式标注 + 创建 session。

        成功 → _kernel_mode="argosd", _with_daemon=True, _daemon_client/session_id 就绪。
        失败 → _kernel_mode="inline", _with_daemon=False(inline fallback,诚实标注)。
        Demo 模式跳过(demo=True 时不调本方法)。
        """
        import os
        from argos.tui.daemon_spawn import probe_or_spawn
        from argos.daemon.client import DaemonClient

        # ARGOS_NO_DAEMON=1 总开关:强制 inline(测试隔离铁律 —— pytest 绝不许探测/
        # 连接用户真实 daemon,否则测试会在用户内核上建 session/run;实测 2026-06-12:
        # 真 daemon 在跑时 7 个 TUI 测试漏连上去吃 403)。也供 headless 用户显式关闭。
        if os.environ.get("ARGOS_NO_DAEMON") == "1":
            self._kernel_mode = "inline"
            self._with_daemon = False
            try:
                self.query_one("#status-bar", StatusBar).set_kernel_mode("inline(单进程)")
            except Exception:  # noqa: BLE001
                pass
            return

        socket_path = Path(os.environ.get("ARGOS_DAEMON_SOCKET", "~/.argos/daemon.sock")).expanduser()

        ready = await probe_or_spawn(socket_path)
        if not ready:
            # inline fallback 模式(daemon 尝试拉起但失败/超时)
            self._kernel_mode = "inline"
            self._with_daemon = False
            try:
                self.query_one("#status-bar", StatusBar).set_kernel_mode("inline(单进程)")
            except Exception:  # noqa: BLE001
                pass
            # #30:尝试拉起 daemon 失败后,在 transcript 落一条系统说明(诚实标注)。
            # ARGOS_NO_DAEMON=1 明确关闭时不显示(那是用户主动选择 inline,不是 fallback)。
            try:
                self.run_worker(
                    self.query_one("#transcript", Transcript).append_line(
                        "daemon 不可用,已切换到单进程模式(后台化 / 跨会话续跑不可用)。",
                        kind="system",
                    ),
                    exclusive=False,
                )
            except Exception:  # noqa: BLE001
                pass
            return

        # daemon 就绪:创建 session
        client = DaemonClient(socket_path)
        try:
            sid = await client.create_session()
        except Exception as e:  # noqa: BLE001
            # 创建 session 失败:退到 inline(诚实)
            import logging as _log
            _log.getLogger(__name__).warning("daemon session create failed: %s", e)
            self._kernel_mode = "inline"
            self._with_daemon = False
            try:
                self.query_one("#status-bar", StatusBar).set_kernel_mode("inline(单进程)")
            except Exception:  # noqa: BLE001
                pass
            # #30:session 创建失败也属于 daemon 不可用,同样落说明行
            try:
                self.run_worker(
                    self.query_one("#transcript", Transcript).append_line(
                        "daemon 不可用,已切换到单进程模式(后台化 / 跨会话续跑不可用)。",
                        kind="system",
                    ),
                    exclusive=False,
                )
            except Exception:  # noqa: BLE001
                pass
            return

        self._daemon_client = client
        self._daemon_session_id = sid
        self._kernel_mode = "argosd"
        self._with_daemon = True
        try:
            self.query_one("#status-bar", StatusBar).set_kernel_mode("argosd")
        except Exception:  # noqa: BLE001
            pass

    # ── 工作态边缘光(spec §工作态边缘光) ─────────────────────────────────
    def _set_border(self, color) -> None:
        self.screen.styles.border = ("round", color)

    def _set_terminal_glow(self, active: bool, *, kind: str = "fail") -> None:
        """边框告警锁色 + StatusBar 告警态联动(spec §8.4 / 陷阱2)。

        `_terminal_glow` 与 StatusBar `-alert` 同源:failed/unverifiable/escalation/error 置 True,
        新 run / plan 解锁置 False。StatusBar 锁色后阶段眼仍随 phase,整条锁语义色——
        kind="fail" 红(failed/error),kind="warn" 橙(unverifiable/escalation)。阶段色不得覆盖。
        StatusBar 未 mount(测试直构)时静默(陷阱1 模式)。"""
        self._terminal_glow = active
        try:
            self.query_one("#status-bar", StatusBar).set_alert(active, kind=kind)
        except Exception:  # noqa: BLE001 — 未 mount / 测试场景:状态已在 _terminal_glow 字段里
            pass

    def _glow_start(self) -> None:
        from argos.tui import glow
        self._set_terminal_glow(False)        # 新一轮:解锁告警色(边框 + StatusBar -alert)
        self._glow_phase = 0.0
        self._glow_base = glow.phase_color("plan")
        self._set_border(self._glow_base)
        if self._glow_timer is None:          # 起呼吸计时器(边框色 set_interval 重设,glow 可行性研究已证安全无闪烁)
            self._glow_timer = self.set_interval(0.1, self._glow_breathe)

    def _glow_breathe(self) -> None:
        """非终态时把当前阶段基色按 breathe 调亮暗(呼吸);终态告警色静止不呼吸。"""
        from argos.tui import glow
        if self._terminal_glow or self._glow_base is None:
            return
        self._glow_phase = (self._glow_phase + 0.03) % 1.0   # 步长 0.03/0.1s tick → ~3.3s 一个呼吸周期(平静呼吸,非快速脉冲)
        self._set_border(glow.breathe(self._glow_base, self._glow_phase))

    def _glow_stop(self) -> None:
        from argos.tui import glow
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
        from argos.tui import glow
        for sp in self.query(StartupSplash):
            sp.set_plan_mode(self._plan_mode)
        try:
            self.query_one("#status-bar", StatusBar).set_plan_mode(self._plan_mode)
        except Exception:  # noqa: BLE001 — 测试中或在 on_mount 前调,status_bar 还没 mount,静默
            pass
        self.sub_title = self._compose_subtitle()
        self._refresh_topbar()
        if self._plan_mode and not self._run_active:
            # idle 切 plan mode 时把边框也换到 plan 基色(不呼吸 —— run 期间再由 _glow_start 接管)
            self._set_border(glow.phase_color("plan"))

    # ── 输入分发 ──────────────────────────────────────────────────────────
    def on_prompt_area_submitted(self, event: PromptArea.Submitted) -> None:
        # PromptArea 已在内部清空自身;这里只负责分发(slash / goal)。同时收掉 slash 菜单。
        self.query_one("#slash-menu", SlashMenu).hide()
        self.handle_input(event.text, event.attachments)

    # ── 语音输入编排(voice input Task 5)──────────────────────────────────────

    def _get_recorder(self):
        if self._voice_recorder is None:
            self._voice_recorder = Recorder()
        return self._voice_recorder

    def _get_transcriber(self):
        if self._voice_transcriber is None:
            self._voice_transcriber = make_transcriber(load_stt_config())
        return self._voice_transcriber

    async def on_prompt_area_voice_toggle(self, event) -> None:
        await self._voice_toggle()

    async def _voice_toggle(self) -> None:
        """开/停录音 → 转写 → 注入输入框(load_text/insert,不模拟粘贴)。
        每条失败路径诚实落 transcript,不崩、不伪绿。转写不自动提交,由用户回车。"""
        import asyncio
        log = self.query_one("#transcript", Transcript)
        if not self._voice_recording:
            try:
                self._get_recorder().start()
            except RecorderError as e:
                await log.append_line(f"⚠︎ 录音失败:{e}", kind="error")
                return
            self._voice_recording = True
            await log.append_line("🎙 录音中…(再按空格停止)", kind="system")
            return
        # 停止 → 转写
        self._voice_recording = False
        try:
            audio = self._get_recorder().stop()
        except RecorderError as e:
            await log.append_line(f"⚠︎ 录音失败:{e}", kind="error")
            return
        transcriber = self._get_transcriber()
        # 首次使用本地语音:权重可能要从 HuggingFace 懒下载(约数百 MB),静默"转写中…"会像卡死。
        # 首次本地转写给更诚实的标签(可能下载),日常转写照旧"转写中…"(2026-06-18 排查 #4)。
        first_local = (not self._stt_warmed) and isinstance(transcriber, LocalWhisper)
        await log.show_thinking(
            "首次使用·加载语音模型(若未缓存需下载约数百 MB,请稍候)…" if first_local else "转写中…"
        )
        try:
            text = await asyncio.to_thread(transcriber.transcribe, audio)
        except SttError as e:
            await log.append_line(f"⚠︎ 转写失败:{e}", kind="error")
            return
        self._stt_warmed = True
        if text:
            self.query_one("#prompt", PromptArea).insert(text)

    # ── #5b 多 run tab 切换 ────────────────────────────────────────
    def on_tab_strip_tab_activated(self, event: TabActivated) -> None:
        """TabStrip 发 TabActivated → 调 focus POST + 切 active 标识。"""
        self.run_worker(self._on_tab_activated(event.run_id), exclusive=False)

    async def _on_tab_activated(self, run_id: str) -> None:
        """user 激活某 tab:调 focus 端点 + 切 active + 更新 TabStrip 视觉。

        observer 调 /focus 拿 403 — 我们不假装成功,在 transcript 落 READ-ONLY 提示。
        """
        if not self._with_daemon or not self._daemon_client or not self._daemon_session_id:
            return
        try:
            status, _, raw = await self._daemon_client._request(
                "POST", f"/runs/{run_id}/focus", session_id=self._daemon_session_id,
            )
        except Exception as e:  # noqa: BLE001
            # 403 / daemon 失联等 — 落行告知
            try:
                log_widget = self.query_one(Transcript)
                await log_widget.append_line(
                    f"⚠︎ focus 失败({run_id[:8]}…):{e}", kind="error",
                )
            except Exception:  # noqa: BLE001
                pass
            return
        # 切 active run_id
        self._daemon_run_id = run_id
        # 同步更新 TabStrip 的 active
        try:
            strip = self.query_one(TabStrip)
            strip.set_active(run_id)
        except Exception:  # noqa: BLE001
            pass
        # 重置 Esc 双击检测(切 tab 避免误触发)
        self._last_esc_time = 0.0
        # 拉新 run 的 events 重放(transcript 清空 + replay)
        self.run_worker(self._replay_run_to_transcript(run_id), exclusive=False)

    async def _replay_run_to_transcript(self, run_id: str) -> None:
        """切到新 run → 清空本地 transcript → 拉 events 重新渲染。

        简化:本期仅落一行标记,真 replay 走 SSE 订阅时即时渲染;
        切到新 run 时,我们已绑 SSE 订阅进 produce worker(下个 task),SSE 收的事件按 EventBus
        走 _apply_event 全套渲染路径,自动重放 run 期间所有事件。
        """
        try:
            log_widget = self.query_one(Transcript)
            await log_widget.append_line(
                f"━━━ 切到 run {run_id[:8]}… ━━━", kind="system",
            )
        except Exception:  # noqa: BLE001
            pass

    def _refresh_tab_strip(self) -> None:
        """从 daemon 拉所有 run 列表 → 更新 TabStrip(daemon 模式才调)。"""
        if not self._with_daemon or not self._daemon_client or not self._daemon_session_id:
            return
        async def _do():
            try:
                runs = await self._daemon_client.list_runs(self._daemon_session_id)
            except Exception:  # noqa: BLE001
                return
            tabs_data = [
                {
                    "run_id": r["run_id"],
                    "goal": r.get("goal", ""),
                    "state": r.get("state", "pending"),
                    "cost_usd": r.get("cost_usd"),
                }
                for r in runs
            ]
            try:
                strip = self.query_one(TabStrip)
                strip.update_tabs(tabs_data, active=self._daemon_run_id)
            except Exception:  # noqa: BLE001
                pass
        self.run_worker(_do(), exclusive=False)

    def on_text_area_changed(self, event) -> None:
        """输入内容变化 → 驱动 slash 命令菜单(打 / 即列命令;带参/非 slash 则隐藏)。"""
        menu = self.query_one("#slash-menu", SlashMenu)
        menu.show_matches(match_commands(event.text_area.text))

    def _push_input_history(self, text: str) -> None:
        """将提交的文本压入输入历史环形缓冲(去重最近一条;容量 _input_history_max)。"""
        t = text.strip()
        if not t:
            return
        # 避免连续重复
        if self._input_history and self._input_history[-1] == t:
            return
        self._input_history.append(t)
        if len(self._input_history) > self._input_history_max:
            self._input_history.pop(0)

    def handle_input(self, text: str, attachments: list | None = None) -> None:
        """slash 走分发;否则当 goal(可带图片 attachments)。同步入口(测试可直接调)。

        Transcript 落行是 async,故 slash 分发与"任务进行中"提示都包成 worker(测试 pause 后可见)。
        非空提交(goal 或 slash)都压入输入历史环形缓冲,供 ↑/↓ 历史导航回填。"""
        # 提交时压历史(slash 和 goal 都记;/retry /clear 等单次偶用的命令也记,方便重试)
        if text.strip():
            self._push_input_history(text)
        cmd = parse_slash(text)
        if cmd is None:
            if text.strip():
                if self._run_active:
                    # 单会话编码 agent:一轮未完不并发起新轮(否则 step 块串台/漏渲染)。
                    self.run_worker(
                        self.query_one("#transcript", Transcript).append_line(
                            "› 当前任务进行中,请等它结束再起新任务。"
                        ),
                        exclusive=False,
                    )
                    return
                # 非测试同步场景:起一轮 run(测试用 start_run 显式 await)
                self.run_worker(self.start_run(text.strip(), attachments or []), exclusive=False)
            return
        self.run_worker(self._dispatch_slash(cmd), exclusive=False)

    async def _dispatch_slash(self, cmd: SlashCommand) -> None:
        log = self.query_one("#transcript", Transcript)
        if not cmd.known:
            await log.append_line(f"未知命令 /{cmd.name}")
            return
        if cmd.name == "yolo":
            # /yolo 是 /trust autonomous 的别名（保留命令，直接生效；提示新用法）。
            # 与 /trust autonomous 不同：/yolo 不弹升档确认（历史合约；用户明确输入即表示确认）。
            self.gate.set_trust_level(
                __import__("argos.permissions.trust_dial", fromlist=["TrustLevel"]).TrustLevel.L4_AUTONOMOUS
            )
            self._yolo = True
            self.sub_title = self._compose_subtitle()
            self._refresh_topbar()
            await log.append_line(
                "已切换到 Autonomous（全自治/YOLO）——顶栏显示 ⏻ YOLO 标记。"
                " 提示：新用法为 /trust autonomous（或无参数 /trust 循环切换）。",
            )
        elif cmd.name == "trust":
            await self._trust_cmd(log, (cmd.arg or "").strip().lower())
        elif cmd.name == "model":
            from argos import config as _cfg
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
            from argos.tui.commands import COMMAND_HELP
            lines = ["命令(打 / 也会就地列出,Tab 补全):"]
            lines += [f" · /{name:<16} {desc}" for name, desc in COMMAND_HELP.items()]
            lines.append(
                "快捷键:\n"
                "  Esc / Ctrl+C   打断当前任务\n"
                "  Ctrl+C (空闲)  连按两次退出\n"
                "  Ctrl+D         退出\n"
                "  Ctrl+B         后台化当前 run(daemon 模式)\n"
                "  Ctrl+O         循环切换右栏视图\n"
                "  Ctrl+V         从剪贴板粘贴图片\n"
                "  行尾 \\ + 回车  插入换行(多行输入)\n"
                "  ↑ / ↓          浏览输入历史"
            )
            await log.append_line("\n".join(lines), kind="system")
        elif cmd.name == "tools":
            await self._show_tools(log)
        elif cmd.name == "skills":
            self._last_skills_arg = cmd.arg
            await self._show_skills(log)
        elif cmd.name == "mcp":
            await self._show_mcp(log)
        elif cmd.name == "undo":
            await self._undo(log)
        elif cmd.name == "ledger":
            await self._ledger_cmd(log)
        elif cmd.name == "journal":
            await self._journal_cmd(log, cmd.arg)
        elif cmd.name == "setup":
            await self._setup_cmd(log)
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
        elif cmd.name == "orders":
            await self._orders_cmd(log)
        elif cmd.name == "confirm":
            await self._confirm_suggestion_cmd(log, cmd.arg)
        elif cmd.name == "dismiss":
            await self._dismiss_suggestion_cmd(log, cmd.arg)
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
        elif cmd.name == "eval":
            await self._eval_cmd(log, cmd.arg)
        elif cmd.name == "routing":
            await self._routing_cmd(log, cmd.arg)
        elif cmd.name == "context":
            await self._context_cmd(log, cmd.arg)
        elif cmd.name == "dream":
            await self._dream_cmd(log, cmd.arg)

    async def _undo(self, log) -> None:
        """/undo:用本轮 run 起点的快照还原 workspace;不发 goal。"""
        if self._snapshot is None or not self._snapshot.tar_path.exists():
            await log.append_line(
                "无可撤销的运行(本会话尚未启动 run,或快照已清理)。",
                kind="system",
            )
            return
        result = self._snapshot.restore(self._workspace)
        # #9 T5:auto-capture undo 事件
        try:
            from argos.memory import auto as _mem_auto
            from argos.memory.auto import project_id_for as _pid
            reason = "snapshot restored" if not result.errors else f"partial restore ({len(result.errors)} errors)"
            _mem_auto.capture_event("undo", project_id=_pid(self._workspace), reason=reason)
        except Exception:  # noqa: BLE001
            pass
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

    async def _trust_cmd(self, log, arg: str) -> None:
        """/trust [cautious|trusted|autonomous|paranoid|status]:信任模式(3-mode)。

        无参数 → 在 3 个模式间循环(Cautious→Trusted→Autonomous→…，Claude Code Shift+Tab 式)。
        /trust status → 只显示当前模式 + 拨盘,不切换。
        /trust cautious|trusted|autonomous → 切到指定模式;升档先渲染 escalation_warning 经确认。
        /trust paranoid → 隐藏的"每一步都问"档(L0)。降档直接生效(收紧权限,无需确认)。
        /yolo 是 /trust autonomous 的别名(旧兼容命令)。l0-l4 仍作隐藏别名保留。
        """
        from argos.permissions.trust_dial import (
            TrustLevel, escalation_warning, next_in_cycle, to_approval_semantics,
        )

        # 计算当前 TrustLevel(单一真源,与 TopBar Trust 徽标共用)
        current_trust = self._resolve_trust_level()

        # status → 只显示状态,不切换
        if arg in ("status", "s"):
            await log.append_line(
                f"当前信任模式：{current_trust.mode_name}（{current_trust.label_human}）\n{current_trust.description}",
                kind="system",
            )
            await log.mount_block(TrustDial(current=current_trust))
            return

        # 无参数 → 循环到下一个可见模式(Cautious→Trusted→Autonomous→…)
        if not arg:
            target_trust = next_in_cycle(current_trust)
        else:
            # 解析目标模式:3-mode 名为主,l0-l4 / paranoid / auto 为隐藏别名。
            _arg_map: dict[str, TrustLevel] = {
                "cautious": TrustLevel.L1_DANGEROUS_ONLY,
                "trusted": TrustLevel.L3_SESSION_TRUSTED,
                "autonomous": TrustLevel.L4_AUTONOMOUS,
                "auto": TrustLevel.L4_AUTONOMOUS,
                "paranoid": TrustLevel.L0_EVERY_STEP,
                # 隐藏别名(向后兼容)
                "l0": TrustLevel.L0_EVERY_STEP,
                "l1": TrustLevel.L1_DANGEROUS_ONLY,
                "l2": TrustLevel.L2_IRREVERSIBLE_ONLY,
                "l3": TrustLevel.L3_SESSION_TRUSTED,
                "l4": TrustLevel.L4_AUTONOMOUS,
            }
            target_trust = _arg_map.get(arg)
            if target_trust is None:
                await log.append_line(
                    f"未知模式 '{arg}'。用法：/trust [cautious|trusted|autonomous|paranoid|status]"
                    "（无参数则循环切换）",
                    kind="system",
                )
                return

        # 同档位：无需操作
        if target_trust is current_trust:
            await log.append_line(
                f"当前已是 {target_trust.mode_name}（{target_trust.label_human}），无需切换。",
                kind="system",
            )
            return

        # 降档：直接生效（收紧权限，无需确认）
        if int(target_trust) < int(current_trust):
            self.gate.set_trust_level(target_trust)
            self._yolo = (target_trust is TrustLevel.L4_AUTONOMOUS)
            self.sub_title = self._compose_subtitle()
            self._refresh_topbar()
            await log.append_line(
                f"已切换到 {target_trust.mode_name}（{target_trust.label_human}）。",
                kind="done",
            )
            return

        # 升档：必须展示警示并等用户 InlineChoice 确认
        warning_text = escalation_warning(current_trust, target_trust)
        target_name = target_trust.mode_name
        target_label = target_trust.label_human

        def _on_trust_confirm(value: str, _feedback: str) -> None:
            if value == "confirm":
                self.gate.set_trust_level(target_trust)
                self._yolo = (target_trust is TrustLevel.L4_AUTONOMOUS)
                self.sub_title = self._compose_subtitle()
                self._refresh_topbar()
                self.run_worker(
                    log.append_line(
                        f"已升级到 {target_name}（{target_label}）。"
                        + (" TUI 顶栏显示 ⏻ 红色警示灯。" if target_trust is TrustLevel.L4_AUTONOMOUS else ""),
                        kind="done",
                    ),
                    exclusive=False,
                )
            else:
                self.run_worker(
                    log.append_line("已取消升档操作，保持当前档位。", kind="system"),
                    exclusive=False,
                )
            self._choice_done()

        await self._enqueue_choice(lambda: InlineChoice(
            title=f"升档确认 — 切换到 {target_label}",
            body=warning_text,
            options=[("confirm", "确认升档"), ("cancel", "取消，保持当前档位")],
            on_decide=_on_trust_confirm,
            escape_value="cancel",  # fail-closed：Esc = 取消
            risk="high" if target_trust is TrustLevel.L4_AUTONOMOUS else "medium",
        ))

    async def _ledger_cmd(self, log) -> None:
        """/ledger:列出当前 run 的行为账本(人话条目 + 撤销状态着色)。

        来源优先级:
          1. 若存在 _ledger_store(daemon 路径注入),直接从 store 读当前 run 账本。
          2. 否则诚实提示"当前会话无账本"(demo/inline 路径无账本记录)。
        复用 transcript 渲染,不加新 widget。
        撤销状态着色:available=绿,done=灰,impossible=红。
        """
        ledger_store = getattr(self, "_ledger_store", None)
        run_id = getattr(self, "_daemon_run_id", None) or getattr(self, "_run_id", None)

        if ledger_store is None or run_id is None:
            await log.append_line(
                "当前会话无行为账本(账本仅在 daemon 模式下可用,或本轮 run 尚未产生副作用动作)。",
                kind="system",
            )
            return

        try:
            entries = ledger_store.replay(run_id)
        except Exception as e:  # noqa: BLE001
            await log.append_line(f"账本读取失败:{e}", kind="error")
            return

        if not entries:
            await log.append_line(
                f"run {run_id} 尚无账本记录(本轮 run 未产生副作用动作)。",
                kind="system",
            )
            return

        # 过滤掉 undo_done 哨兵条目(action=undo_done 是内部标记,不对用户显示)
        visible = [e for e in entries if e.action != "undo_done"]
        if not visible:
            await log.append_line(
                f"run {run_id} 账本:所有动作均已撤销。",
                kind="system",
            )
            return

        # 检查是否有文件粒度可撤条目(undo_token 含 "file:" 前缀)
        has_file_undo = any(
            e.undo_state == "available"
            and e.undo_token
            and e.undo_token.startswith("file:")
            for e in visible
        )

        widget = LedgerTable(entries=visible, run_id=run_id)
        await log.mount_block(widget)
        journal_path = Path.home() / ".argos" / "ledger" / f"{run_id}.jsonl"
        await log.append_line(
            f"每条回执签名 · summary 模板生成不调模型\n"
            f"journal: {journal_path}  (/journal {run_id} 查路径)",
            kind="system",
        )

    async def _setup_cmd(self, log) -> None:
        """/setup:显示配置向导入口。TUI 内无法直接运行 argos setup(它是交互式 CLI);
        诚实告知路径,让用户退出后运行。"""
        await log.append_line(
            "配置向导\n"
            "  退出 TUI 后运行:\n"
            "    argos setup\n"
            "  向导会引导你填写 provider、API key,并做连通性测试,\n"
            "  结果写入 ~/.argos/.env 和 ~/.argos/config.json。\n"
            "  也可手动编辑 ~/.argos/.env 添加 ANTHROPIC_API_KEY=... 等环境变量。",
            kind="system",
        )

    async def _journal_cmd(self, log, arg: str) -> None:
        """/journal [run_id]:显示账本 JSONL 的绝对路径。

        有 run_id → 显示指定 run 的路径;无参数 → 显示当前 run 的路径(若有)。
        任意情况下都只打路径,不尝试读文件内容(避免在 TUI 里输出大量 JSONL)。
        """
        ledger_dir = Path.home() / ".argos" / "ledger"
        run_id = arg.strip() or getattr(self, "_daemon_run_id", None) or getattr(self, "_run_id", None)
        if run_id:
            journal_path = ledger_dir / f"{run_id}.jsonl"
            await log.append_line(
                f"账本 JSONL: {journal_path}\n"
                f"  查看:cat {journal_path}\n"
                f"  实时跟踪:tail -f {journal_path}",
                kind="system",
            )
        else:
            await log.append_line(
                f"账本目录: {ledger_dir}\n"
                "  当前会话暂无 run_id(未起 run 或非 daemon 模式)。\n"
                "  用法:/journal <run_id>",
                kind="system",
            )

    async def _retry(self, log) -> None:
        """/retry:重发本 session 最后一条 user 消息。busy / 空 / 无 store 诚实报。

        改进:若 _input_history 有记录,先把上一条 goal 回填到输入框(#20 历史导航),
        再执行 start_run。
        实现简化:demo 模式(FakeLoop,无 store)下诚实报"当前 store 不支持"——
        真模式需要 build_components 把 store 注入到 App(self._store 字段),
        那是更大装配改动,留作下一 PR。
        """
        if self._run_active:  # busy 守卫(实际字段是 _run_active,非 _busy)
            await log.append_line("先 Esc 打断当前任务,再 /retry。", kind="system")
            return
        # 优先从输入历史取上一条(最近提交的 goal/slash;不需要 store):
        # 找最后一条非 slash(非 / 开头)的历史条目作为 retry goal。
        last_goal: str | None = None
        for entry in reversed(getattr(self, "_input_history", []) or []):
            if not entry.startswith("/"):
                last_goal = entry
                break
        if last_goal:
            # 回填输入框(#20)
            try:
                prompt_widget = self.query_one("#prompt", PromptArea)
                prompt_widget._refill(last_goal)
                prompt_widget.reset_history_nav()
            except Exception:  # noqa: BLE001
                pass
            await self.start_run(last_goal)
            return
        # 无历史:降级到 store 路径(原有逻辑)
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
        from argos.core.plan_mode import EnterPlanMode
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
        from argos.hooks import get_config, reload_config, HooksConfigError
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
        from argos import lsp as _lsp
        from argos.lsp import get_config, reload_config, LspConfigError
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
        from argos.permissions import (
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
        """/tools:列出 agent 可调用的全部工具(诚实:数量 = 真实可调用工具数)。

        P3 动态化：names 从 registry.names() 派生（诚实计数）；无 registry 时退静态表。
        """
        from argos import tools as _tools
        # 优先从当前 loop 的 broker._registry 取（P3 动态来源）；无则退静态表。
        _registry = None
        _loop = getattr(self, "_current_loop", None)
        if _loop is not None:
            _broker = getattr(_loop, "_broker", None) or getattr(_loop, "broker", None)
            if callable(_broker):   # property
                try:
                    _broker = _broker()
                except Exception:   # noqa: BLE001
                    _broker = None
            if _broker is not None:
                _registry = getattr(_broker, "_registry", None)
        names = _tools.get_tool_names(_registry)
        # 诚实:工作流默认关闭(ARGOS_WORKFLOWS 未设时 host 不 dispatch propose_workflow)——
        # 注明这点,别让 /tools 把一个默认 inert 的工具显示成立即可用。
        import os as _os_wf
        _wf_label = "编排(工作流)" if _os_wf.environ.get("ARGOS_WORKFLOWS") else "编排(工作流,需 ARGOS_WORKFLOWS=1 才执行)"
        groups = [
            ("文件", ["read_file", "write_file", "edit_file", "search_files"]),
            ("命令/验证/计划", ["run_command", "propose_verify", "update_plan"]),
            ("联网", ["web_search", "web_extract"]),
            ("计算机控制(浏览器)", [n for n in names if n.startswith("browser_")]),
            ("外部工具", ["mcp_call"]),
            ("LSP 语言服务器", [n for n in names if n.startswith("lsp_")]),
            # 模型可见名=下划线(ALL_TOOL_NAMES 路径);registry.names() 仍点号 —— 两者都归此组。
            ("OS 级控制(P6a)", [n for n in names
                                if n.startswith("computer_")]),
            (_wf_label, ["propose_workflow"]),
        ]
        lines = [f"共 {len(names)} 个工具:"]
        for label, members in groups:
            present = [m for m in members if m in names]
            if present:
                lines.append(f" · {label}:{', '.join(present)}")
        await log.append_line("\n".join(lines), kind="system")

    async def _runs_cmd(self, log, arg: str) -> None:
        """/runs / /runs {id} focus|resume|cancel — daemon 模式 run 列表与控制(spec §2.6 e + #5b §8)。

        无 daemon 时 → 报"未启用 daemon";有 daemon → 列 run + 代理 pause/resume/cancel/focus。
        #5b 扩展:列 run 时显示 cost + worktree + observer 标识(owner vs readonly)。
        """
        if not self._with_daemon or not self._daemon_client or not self._daemon_session_id:
            await log.append_line(
                "未启用 daemon(--with-daemon flag);/runs 不可用。",
                kind="system",
            )
            return
        # #5b observer 标识
        rec = self._daemon_client.__class__  # type: ignore[attr-defined]
        # 用 daemon sessions 表查 role(client 端无 sessions 查,fallback:不加 banner)
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
            from argos.tui.widgets.tab_strip import _format_cost
            _ICON = {
                "pending": "◌", "running": "◉", "paused": "◔",
                "suspended": "◌", "completed": "◕",
                "failed": "◉", "cancelled": "◌",
            }
            lines = ["Run 列表(#5b 扩展:cost / worktree):"]
            for r in runs:
                icon = _ICON.get(r.get("state", "pending"), "◌")
                age = int(_time.time() - r.get("created_at", 0))
                cost = _format_cost(r.get("cost_usd"))
                wt = r.get("worktree_path") or ""
                wt_short = (wt.split("/")[-1] if wt else "(none)")[:20]
                focus_tag = " ★" if r.get("focus_session_id") == self._daemon_session_id else ""
                lines.append(
                    f" · {icon} {r['run_id']}  {r['state']:<10}  "
                    f"{r['goal'][:32]}  {cost}  [{wt_short}]{focus_tag}  ({age}s ago)"
                )
            lines.append("")
            lines.append("/runs {id} focus|resume|cancel — 控制")
            await log.append_line("\n".join(lines), kind="system")
            return
        # /runs {id} [focus|resume|cancel]
        run_id = parts[0]
        action = parts[1].strip() if len(parts) > 1 else "info"
        if action == "focus":
            # #5b:owner-only;observer 拿 403
            try:
                status, _, _ = await self._daemon_client._request(
                    "POST", f"/runs/{run_id}/focus", session_id=self._daemon_session_id,
                )
                if status == 200:
                    self._daemon_run_id = run_id
                    await log.append_line(
                        f"已 focus {run_id}(active 切到该 run)。",
                        kind="system",
                    )
                    self._refresh_tab_strip()
                else:
                    await log.append_line(
                        f"focus 失败:HTTP {status}", kind="error",
                    )
            except Exception as e:  # noqa: BLE001
                err = str(e)
                if "session_readonly" in err or "403" in err:
                    await log.append_line(
                        "READ-ONLY 观察者不能 focus(只有 owner TUI 能切 active)。",
                        kind="error",
                    )
                else:
                    await log.append_line(f"focus 失败:{e}", kind="error")
            return
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
                from argos.tui.widgets.tab_strip import _format_cost
                cost = _format_cost(info.get("cost_usd"))
                wt = info.get("worktree_path") or "(none)"
                journal_path = Path.home() / ".argos" / "ledger" / f"{run_id}.jsonl"
                await log.append_line(
                    f"{run_id}: state={info.get('state')}  events={info.get('events_count')}  "
                    f"cost={cost}  worktree={wt}\n"
                    f"  journal: {journal_path}",
                    kind="system",
                )
            except Exception as e:  # noqa: BLE001
                await log.append_line(f"查 run 失败:{e}", kind="error")

    # ── P5b §9 自治面：/orders /confirm /dismiss ──────────────────────

    async def _orders_cmd(self, log) -> None:
        """/orders:列出当前 conductor 常驻指令（通过 daemon 或本地 OrderStore）。

        优先走 daemon 端点（/orders）；无 daemon 时直接读本地 OrderStore。
        只读展示，不执行任何自治动作。
        """
        if self._with_daemon and self._daemon_client and self._daemon_session_id:
            try:
                status, _, raw = await self._daemon_client._request(
                    "GET", "/orders", session_id=self._daemon_session_id,
                )
                import json as _json
                orders = _json.loads(raw)
            except Exception as e:  # noqa: BLE001
                await log.append_line(f"/orders 请求失败（daemon）:{e}", kind="error")
                return
        else:
            # 无 daemon：本地 OrderStore 直读
            try:
                from argos.conductor.orders import OrderStore
                orders = [o.to_dict() for o in OrderStore().list()]
            except Exception as e:  # noqa: BLE001
                await log.append_line(f"读取本地 orders 失败:{e}", kind="error")
                return

        from argos.tui.widgets.transcript import Transcript
        await self.query_one("#transcript", Transcript).mount_block(OrdersPanel(orders=orders))

    async def _confirm_suggestion_cmd(self, log, suggestion_id: str) -> None:
        """/confirm <suggestion_id>:用户确认 conductor 建议 → 通过 daemon 端点 create_run。

        TUI 只是 daemon 客户端，真正的确认通过 POST /suggestions/{id}/confirm（daemon 侧）。
        铁律：isolation=worktree + trust_level=L1_DANGEROUS_ONLY（server 端写死，TUI 不可覆盖）。
        """
        suggestion_id = suggestion_id.strip()
        if not suggestion_id:
            await log.append_line("用法:/confirm <suggestion_id>", kind="error")
            return
        if not self._with_daemon or not self._daemon_client or not self._daemon_session_id:
            await log.append_line(
                "confirm 需要 daemon 模式（--with-daemon）。",
                kind="error",
            )
            return
        try:
            status, _, raw = await self._daemon_client._request(
                "POST", f"/suggestions/{suggestion_id}/confirm",
                session_id=self._daemon_session_id,
            )
            import json as _json
            body = _json.loads(raw) if raw else {}
        except Exception as e:  # noqa: BLE001
            await log.append_line(f"/confirm 请求失败:{e}", kind="error")
            return
        if status == 201:
            run_id = body.get("run_id", "?")
            wt = body.get("worktree_path") or "(none)"
            await log.append_line(
                f"建议已确认并创建 run：{run_id}\n"
                f"  隔离：worktree={wt}\n"
                f"  信任档：L1_DANGEROUS_ONLY（写死，不可升级）\n"
                f"  用 /runs 查看运行状态。",
                kind="done",
            )
        elif status == 404:
            await log.append_line(
                f"建议 {suggestion_id!r} 未找到或已处理（dismissed/confirmed）。",
                kind="error",
            )
        elif status == 503:
            await log.append_line(
                f"无法确认：{body.get('error', '服务暂不可用')}",
                kind="error",
            )
        else:
            await log.append_line(
                f"/confirm 失败（HTTP {status}）：{body.get('error', raw)}",
                kind="error",
            )

    async def _dismiss_suggestion_cmd(self, log, suggestion_id: str) -> None:
        """/dismiss <suggestion_id>:忽略 conductor 建议（通过 daemon 端点）。"""
        suggestion_id = suggestion_id.strip()
        if not suggestion_id:
            await log.append_line("用法:/dismiss <suggestion_id>", kind="error")
            return
        if not self._with_daemon or not self._daemon_client or not self._daemon_session_id:
            await log.append_line(
                "dismiss 需要 daemon 模式（--with-daemon）。",
                kind="error",
            )
            return
        try:
            status, _, raw = await self._daemon_client._request(
                "POST", f"/suggestions/{suggestion_id}/dismiss",
                session_id=self._daemon_session_id,
            )
            import json as _json
            body = _json.loads(raw) if raw else {}
        except Exception as e:  # noqa: BLE001
            await log.append_line(f"/dismiss 请求失败:{e}", kind="error")
            return
        if status == 200:
            await log.append_line(f"建议 {suggestion_id!r} 已忽略。", kind="system")
        elif status == 404:
            await log.append_line(
                f"建议 {suggestion_id!r} 未找到或已处理。",
                kind="error",
            )
        else:
            await log.append_line(
                f"/dismiss 失败（HTTP {status}）：{body.get('error', raw)}",
                kind="error",
            )

    # ── TUI ProactiveSuggestionEvent 渲染 ────────────────────────────

    async def _on_proactive_suggestion(self, ev) -> None:
        """ProactiveSuggestionEvent 渲染：ConductorSuggestionChoice 决策卡。

        真正的确认通过 POST /suggestions/{id}/confirm（daemon 端点）。
        fail-closed：Esc = dismiss，绝不自动执行。
        """
        def _decide(value: str, _feedback: str) -> None:
            from argos.tui.widgets.transcript import Transcript as _Transcript
            try:
                _log = self.query_one("#transcript", _Transcript)
            except Exception:  # noqa: BLE001
                _log = None
            if value == "confirm":
                if _log is not None:
                    self.run_worker(self._confirm_suggestion_cmd(_log, ev.suggestion_id), exclusive=False)
            else:
                if _log is not None:
                    self.run_worker(self._dismiss_suggestion_cmd(_log, ev.suggestion_id), exclusive=False)
            self._choice_done()

        try:
            await self._enqueue_choice(lambda: ConductorSuggestionChoice(ev=ev, on_decide=_decide))
        except Exception:  # noqa: BLE001
            pass

    # ── TUI ComputerActionEvent 渲染(P6a §10)────────────────────────

    async def _on_computer_action(self, ev: "ComputerActionEvent") -> None:  # type: ignore[name-defined]
        """ComputerActionEvent 渲染:活动栏/transcript 一行人话。

        渲染原则:
          · 展示【动作类型】+【关键参数(坐标/截断文本)】+【成功/失败】。
          · text_preview 已截断 80 字符(敏感输入不全量进事件流,spec §10)。
          · ok=False 时追加 detail(含权限指引);不展示原始异常栈。
          · screenshot 成功:不单独产出"验证通过"——只记录存档路径。
        """
        from argos.tui.widgets.transcript import Transcript
        try:
            log = self.query_one("#transcript", Transcript)
        except Exception:  # noqa: BLE001 — 未 mount / narrow
            return

        kind = ev.kind_action
        ok_mark = "✓" if ev.ok else "✗"

        if kind == "screenshot":
            if ev.ok:
                path_hint = f" → {ev.artifact_path}" if ev.artifact_path else ""
                line = f"[computer] {ok_mark} 截图已保存{path_hint}"
            else:
                line = f"[computer] {ok_mark} 截图失败:{ev.detail}"
        elif kind in ("click", "double_click"):
            label = "双击" if kind == "double_click" else "点击"
            coord = f"({ev.x}, {ev.y})" if ev.x is not None and ev.y is not None else "(未知坐标)"
            line = f"[computer] {ok_mark} {label}了 {coord}" + (f":{ev.detail}" if not ev.ok else "")
        elif kind == "type_text":
            preview = ev.text_preview[:40] + ("…" if len(ev.text_preview) > 40 else "") if ev.text_preview else ""
            if ev.ok:
                line = f"[computer] {ok_mark} 输入了 {preview!r}" if preview else f"[computer] {ok_mark} 键入文本"
            else:
                line = f"[computer] {ok_mark} 键入失败:{ev.detail}"
        elif kind == "key":
            preview = ev.text_preview or ""
            line = f"[computer] {ok_mark} 按键 {preview!r}" + (f":{ev.detail}" if not ev.ok else "")
        elif kind == "scroll":
            coord = f"({ev.x}, {ev.y})" if ev.x is not None and ev.y is not None else ""
            line = f"[computer] {ok_mark} 滚动{coord}" + (f":{ev.detail}" if not ev.ok else "")
        elif kind == "open_app":
            app_hint = ev.text_preview or ev.detail
            line = f"[computer] {ok_mark} 启动应用 {app_hint}" + ("" if ev.ok else f":{ev.detail}")
        else:
            line = f"[computer] {ok_mark} {kind}:{ev.detail}"

        kind_str = "system" if ev.ok else "error"
        try:
            await log.append_line(line, kind=kind_str)
        except Exception:  # noqa: BLE001
            pass

    async def _skill_cmd(self, log, skill_name: str, arg: str) -> None:
        """/verify / /security-review / /simplify 统一入口(spec §2.6 / §2.7)。

        解析 path → run_skill → chat 追加 summary + findings 表格。
        """
        from pathlib import Path as _P
        from argos.skills_runtime.analysis import AnalysisSkillContext
        from argos.skills_runtime import run_skill, register_builtin_skills

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
        from argos.memory import auto as _mem
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
        from argos.memory import auto as _mem
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
        from argos.memory import auto as _mem
        pid = _mem.project_id_for()
        sid = self._session_id
        text = _mem.view_all(project_id=pid, session_id=sid)
        await log.append_line(text, kind="system")

    async def _eval_cmd(self, log, arg: str) -> None:
        """/eval [run <id> | compare <a> <b>] — Agent 自我评估 + A/B 对比(#7)。

        - 无参:列最近 20 run + 7d pass rate
        - run <task_id>:跑单个 task(走 config active model)
        - compare <a> <b>:<a> / <b> 形如 `<task_id>:<model>`,或纯 run_id
        """
        import time as _time
        from argos.eval.results import list_runs, summary
        if not arg.strip():
            runs = list_runs(limit=20)
            if not runs:
                await log.append_line(
                    "尚未跑过 eval。试试 /eval run <task_id> 或 argos eval corpus",
                    kind="system")
                return
            lines = [
                "最近 eval runs(最多 20):",
                (f"  {'Date':<11} {'Task':<32} {'Tier':<10} {'Status':<14} "
                 f"{'Cost':<8} {'Time':<5}"),
            ]
            for r in runs:
                cost = f"${r.cost_usd:.4f}" if r.cost_usd is not None else "$N/A"
                lines.append(
                    f"  {_time.strftime('%Y-%m-%d', _time.localtime(r.finished_at)):<11} "
                    f"{r.task_id:<32} {r.model_tier:<10} {r.pass_status:<14} "
                    f"{cost:<8} {r.duration_s:.0f}s")
            s = summary()
            if s:
                lines.append("\nPass rate (last 7d):")
                for m, cats in s.items():
                    lines.append(f"  {m}:")
                    for c, stats in cats.items():
                        lines.append(
                            f"    {c:<14} {stats['passed']}/{stats['total']} "
                            f"({stats['pass_rate']*100:.0f}%)")
            await log.append_line("\n".join(lines), kind="system")
            return
        # 有参:解析 "run <id>" / "compare <a> <b>"
        parts = arg.split()
        if parts[0] == "run" and len(parts) == 2:
            await self._eval_run_cmd(log, parts[1])
            return
        if parts[0] == "compare" and len(parts) == 3:
            await self._eval_compare_cmd(log, parts[1], parts[2])
            return
        await log.append_line(
            "用法:/eval [run <task_id> | compare <a> <b>]", kind="error")

    async def _eval_run_cmd(self, log, task_id: str) -> None:
        """/eval run <task_id>:跑单个 task(走 EvalRunner)。"""
        from argos.eval.corpus import load_task
        from argos.eval.runner import EvalRunner, PASS_PASSED
        from argos.eval.results import append as append_result
        from argos.daemon.worktree import WorktreeManager
        try:
            task = load_task(task_id)
        except FileNotFoundError as e:
            await log.append_line(f"未找到 task: {e}", kind="error")
            return
        # 用 config active model(本期不热切换)
        model_tier = "default"
        try:
            from argos import config as _cfg
            if _cfg._has_config_file():
                model_tier = _cfg.load_config().active
        except Exception:  # noqa: BLE001
            pass
        base = Path.home() / ".argos" / "eval"
        await log.append_line(
            f"[eval] task={task.id} category={task.category} difficulty={task.difficulty} "
            f"model={model_tier}")
        wm = WorktreeManager(base_dir=base / "worktrees")
        runner = EvalRunner(worktree=wm, base_dir=base)
        result = runner.run(task, model_tier=model_tier)
        append_result(result, base=base)
        cost = f"${result.cost_usd:.4f}" if result.cost_usd is not None else "$N/A"
        await log.append_line(
            f"[eval] {result.pass_status}  cost={cost}  duration={result.duration_s:.0f}s  "
            f"steps={result.steps}  run_id={result.run_id}",
            kind="done" if result.pass_status == PASS_PASSED else "error",
        )
        if result.error:
            await log.append_line(f"[eval] error: {result.error}", kind="error")

    async def _eval_compare_cmd(self, log, a: str, b: str) -> None:
        """/eval compare <a> <b>:A/B side-by-side,渲 markdown 报告到 transcript。"""
        from argos.eval.corpus import load_task
        from argos.eval.compare import run_pair, write_report
        from argos.eval.runner import EvalRunner
        from argos.daemon.worktree import WorktreeManager
        # 解析 a/b:<task_id>:<model> 或纯 <task_id>(默认 = 同一 model 两遍)
        def _parse(spec: str) -> tuple[str | None, str | None]:
            if ":" in spec:
                tid, m = spec.split(":", 1)
                return tid, m
            return spec, None
        ta, ma = _parse(a)
        tb, mb = _parse(b)
        if not (ta and tb):
            await log.append_line(
                "用法:/eval compare <task_id>[:<model>] <task_id>[:<model>]", kind="error")
            return
        if ta != tb:
            await log.append_line(f"task_id 不一致:{ta} vs {tb}", kind="error")
            return
        try:
            task = load_task(ta)
        except FileNotFoundError as e:
            await log.append_line(f"未找到 task: {e}", kind="error")
            return
        # model 缺省 = active
        active = "default"
        try:
            from argos import config as _cfg
            if _cfg._has_config_file():
                active = _cfg.load_config().active
        except Exception:  # noqa: BLE001
            pass
        ma = ma or active
        mb = mb or active
        base = Path.home() / ".argos" / "eval"
        await log.append_line(f"[eval] A/B: {ma} vs {mb} on {ta} ...")
        wm = WorktreeManager(base_dir=base / "worktrees")
        runner = EvalRunner(worktree=wm, base_dir=base)
        ra, rb = run_pair(runner, task, model_a=ma, model_b=mb)
        p = write_report(ra, rb, base=base)
        md = p.read_text("utf-8")
        if md.count("\n") > 200:
            await log.append_line(
                md[:8000] + "\n\n... (truncated; 完整报告看:cat " + str(p) + ")",
                kind="system")
        else:
            await log.append_line(md, kind="system")

    async def _routing_cmd(self, log, arg: str) -> None:
        """#11 per-task routing TUI:无参列配置 + 最近 10 步决策;
        set <category> <tier> 改写 ~/.argos/config.json(下次 run 生效)。"""
        parts = arg.strip().split()
        if parts and parts[0] == "set":
            await self._routing_set(log, " ".join(parts[1:]))
            return
        # 无参:列 routing config + history
        router = self._current_router()
        if router is None:
            await log.append_line(
                "/routing 不可用(无 router 注入;demo/fake 模式)。",
                kind="system")
            return
        widget = RoutingTable(routing=router.routing, history=router.history())
        from argos.tui.widgets.transcript import Transcript
        await self.query_one("#transcript", Transcript).mount_block(widget)

    async def _context_cmd(self, log, arg: str) -> None:
        """/context:看当前 LLM 上下文分桶(契约 §12;spec §10)。
        无参 → 文本表格(逐行 markup 着色);--json → 整段 JSON(无 markup)。
        analyzer 失败永不崩 run(降级返全空桶,记 error)。"""
        from argos.context.analyzer import analyze
        from argos.context.render import format_json, format_table
        # 找 loop 实例 / store / workspace;无 loop 实例(罕见 e.g. demo)→ 走空分析
        loop = getattr(self, "_agent_loop", None)
        store = getattr(self, "_store", None)
        workspace = getattr(self, "_workspace", None) or Path.home() / ".argos" / "workspace"
        try:
            b = analyze(loop, store=store, workspace=workspace)  # type: ignore[arg-type]
        except Exception as e:  # noqa: BLE001 — 任何分析失败都降级
            await log.append_line(f"/context 失败:{e}", kind="error")
            return
        if "--json" in arg:
            await log.append_line(format_json(b), kind="info")
            return
        for line in format_table(b).split("\n"):
            await log.append_line(line, kind="info")

    # ── T10 /dream 命令 ──────────────────────────────────────────────────

    @staticmethod
    def _fmt_dream_report(r: dict) -> str:
        """把 Dream 报告 dict 格式化成一行摘要(复用于 /dream status 和 SSE dream_report)。"""
        return (
            f"Dream 完成  "
            f"units={r.get('units_total', 0)}  "
            f"promoted={r.get('promoted', 0)}  "
            f"rejected={r.get('rejected', 0)}  "
            f"skipped={r.get('skipped', 0)}  "
            f"memory_merged={r.get('memory_merged', 0)}  "
            f"memory_archived={r.get('memory_archived', 0)}"
        )

    async def _dream_cmd(self, log, arg: str) -> None:
        """/dream [status]:夜间整合命令。

        无参数 → POST /dream/run(daemon 模式);inline 模式诚实拒绝。
        status → GET /dream/report,null → 诚实空态,有 → 渲染摘要一行。
        """
        import json as _json

        sub = arg.strip().lower()

        # ── inline 模式:诚实拒绝 ─────────────────────────────────────
        if not self._with_daemon or not self._daemon_client or not self._daemon_session_id:
            await log.append_line(
                "Dream 需要 daemon 模式(当前 inline)。\n"
                "提示:重启 Argos 让其自动连接 daemon,或检查 ~/.argos/daemon.sock。",
                kind="system",
            )
            return

        # ── status 子命令 → GET /dream/report ──────────────────────
        if sub == "status":
            try:
                status, _, raw = await self._daemon_client._request(
                    "GET", "/dream/report", session_id=self._daemon_session_id,
                )
                body = _json.loads(raw) if raw else {}
            except Exception as e:  # noqa: BLE001
                await log.append_line(f"/dream report 请求失败:{e}", kind="error")
                return
            if status == 200:
                report = body.get("report")
                if report is None:
                    await log.append_line("暂无 Dream 报告(还没跑过夜间整合)。", kind="system")
                elif not isinstance(report, dict):
                    await log.append_line(
                        f"Dream 报告格式异常(期望 dict,收到 {type(report).__name__})",
                        kind="error",
                    )
                else:
                    await log.append_line(self._fmt_dream_report(report), kind="done")
            else:
                await log.append_line(f"/dream report 失败(HTTP {status})", kind="error")
            return

        # ── 无参数 → POST /dream/run ────────────────────────────────
        try:
            status, _, raw = await self._daemon_client._request(
                "POST", "/dream/run", session_id=self._daemon_session_id,
            )
            body = _json.loads(raw) if raw else {}
        except Exception as e:  # noqa: BLE001
            await log.append_line(f"/dream/run 请求失败:{e}", kind="error")
            return

        if status == 202:
            # 诚实铁律:202 = 已启动(test_daemon_wiring 锁此契约);先发口头确认再挂整合卡。
            await log.append_line("Dream 已启动 · 整合进度见下方。", kind="done")
            self._dream_card = DreamReportCard()
            await log.mount_block(self._dream_card)
        elif status == 409:
            await log.append_line("已有 Dream 在跑,请稍后再试。", kind="system")
        elif status == 503:
            msg = body.get("error") or body.get("state") or "无 worker key"
            await log.append_line(f"Dream 启动失败:{msg}", kind="error")
        else:
            await log.append_line(
                f"/dream/run 返回未知状态 HTTP {status}:{body}", kind="error"
            )

    async def _routing_set(self, log, arg: str) -> None:
        """#11 /routing set <category> <tier>:原子改写 config.json。"""
        import os
        from pathlib import Path
        from argos.config import ConfigError
        from argos.routing.categorizer import TaskCategory
        from argos.routing.config import set_category

        parts = arg.strip().split()
        if len(parts) != 2:
            await log.append_line(
                "用法:/routing set <category> <tier>  "
                f"(8 个合法 category: {[c.value for c in TaskCategory]})",
                kind="error")
            return
        cat_name, tier = parts
        try:
            category = TaskCategory(cat_name)
        except ValueError:
            await log.append_line(
                f"category '{cat_name}' 不存在;8 个合法值:"
                f"{[c.value for c in TaskCategory]}",
                kind="error")
            return
        try:
            config_dir = Path(os.environ.get("ARGOS_CONFIG_DIR")
                              or Path.home() / ".argos")
            set_category(config_dir, category, tier)
        except ConfigError as e:
            await log.append_line(f"/routing set 失败:{e}", kind="error")
            return
        await log.append_line(
            f"已写入 {config_dir}/config.json:"
            f"routing.by_category.{category.value} = {tier}",
            kind="done")

    def _current_router(self):
        """拿当前 run 的 router(若存在);无 router 注入 → None(spec D16 友好提示)。"""
        loop = getattr(self, "_current_loop", None)
        if loop is None:
            return None
        return getattr(loop, "_router", None)

    async def _show_skills(self, log) -> None:
        """/skills:#10 重写:列 installed + available from index + 推荐。

支持子命令(本 TUI **不**直接 install/remove,沿 transcript 提示到 host CLI 跑,
spec 2026-06-07 §7.2 D10:把副作用稳定面缩到 host)。
"""
        # 取上一条 slash 命令的 arg(由 _dispatch_slash 在 call 前 set)
        cmd_arg = getattr(self, "_last_skills_arg", "")
        sub_parts = cmd_arg.split()
        if sub_parts and sub_parts[0] in ("install", "remove", "refresh", "test"):
            sub = sub_parts[0]
            sub_arg = sub_parts[1] if len(sub_parts) > 1 else ""
            hint = (
                f"[skills] TUI 不直装副作用。请到 host 跑:\n"
                f"        $ argos skills {sub} {sub_arg}"
            )
            await log.append_line(hint, kind="system")
            return

        try:
            from argos.skills_curator.capabilities import list_installed
            from argos.skills_curator.index import cache_age_days, load_cache
            from argos.skills_curator.recommend import (
                SessionActivity, build_activity_from_session, recommend,
            )
        except Exception as e:  # noqa: BLE001
            await log.append_line(f"curator 未加载:{e}", kind="error")
            return

        installed = list_installed()
        by_name = {s.name: s for s in installed}
        cache = load_cache()
        lines: list[str] = []
        lines.append(f"Installed skills ({len(installed)}):")
        if not installed:
            lines.append("  (no skills installed;跑 `argos skills refresh` 拉 index)")
        for s in installed:
            flag = "OK" if s.enabled else "OFF"
            flag2 = "" if s.enabled else "  (unreviewed)"
            caps = "[" + ", ".join(s.capabilities) + "]"
            lines.append(f"  {flag:3} {s.name:<20} {s.version:<10} {caps}{flag2}")
        if cache is not None and cache.skills:
            avail = [e for e in cache.skills if e.name not in by_name]
            age = cache_age_days() or 0.0
            lines.append(f"\nAvailable from index ({len(avail)}, last refresh {age:.1f}d ago):")
            for e in avail[:10]:
                caps = "[" + ", ".join(e.capabilities) + "]"
                lines.append(
                    f"  ..  {e.name:<20} {e.version:<10} {caps}  "
                    f'"{e.description[:40]}"'
                )
        try:
            activity = build_activity_from_session()
            recs = recommend(
                activity,
                installed={s.name for s in installed if s.enabled},
                cache=cache,
            )
            if recs:
                lines.append(f"\nRecommended for this session ({len(recs)}):")
                for r in recs[:3]:
                    lines.append(f"  *** {r.name}  -- {r.reason}")
        except Exception:  # noqa: BLE001
            pass
        await log.append_line("\n".join(lines), kind="system")

    async def _show_mcp(self, log) -> None:
        """/mcp:列出 ~/.argos/mcp.json 配置的 MCP server + 已连接工具(诚实:不谎报连接态)。"""
        try:
            from argos import mcp_native
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
    async def start_run(self, goal: str, attachments: list | None = None) -> None:
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
        self._current_plan_call_id = None  # 每轮清 plan call_id(不跨轮泄漏)。
        self.query_one("#activity", ActivityPanel).reset_run()  # 每轮起手清活动栏(进度/工具/回执)。
        # UserPromptSubmit hook fire(spec §2.5:TUI 端触发,不在 loop 内)
        try:
            from argos import hooks as _hooks
            from argos.hooks.payload import build_user_prompt_payload
            from argos.hooks.events import HookFired as _HookFired
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
        log = self.query_one("#transcript", Transcript)
        await log.user_line(goal)  # 回显用户目标进对话流(› 行),否则对话看着单边(Task 14)。

        # v6 P3b §3:双路 start_run ─────────────────────────────────────────
        # daemon 模式:POST /runs → DaemonEventSource 喂 EventBus → 现有渲染路径零改动。
        # inline 模式:直接 loop.run() → 现有路径(向后兼容,不动)。
        if self._with_daemon and self._daemon_client is not None and self._daemon_session_id:
            await self._start_run_daemon(goal, log, attachments or [])
        else:
            await self._start_run_inline(goal, log, attachments or [])

    async def _start_run_inline(self, goal: str, log, attachments: list | None = None) -> None:
        """inline 路径(单进程直跑):保持原有语义,支持 FakeLoop + AgentLoop。

        plan_decision 走 loop.respond_plan_decision(call_id, action, feedback)——
        彻底去掉 TUI 对 ExitPlanMode 等 loop 内部对象的直接引用(设计 §4 刀2收口)。
        _handle_plan_rendered 已统一经 loop.respond_plan_decision 回传决策。
        """
        bus = EventBus()
        loop = self._loop_factory()
        # Plan mode:把本轮 loop 引用挂到 self;_handle_plan_rendered 经 respond_plan_decision 回传。
        self._current_loop = loop

        # 记忆召回提示行
        await self._announce_memory_recall(log, loop, goal)
        if self._demo:
            await log.append_line(
                "⚠︎ 演示模式:以下为脚本化假数据,非真实执行/验证(真 AgentLoop 待 Phase 6 接入)。"
            )
        else:
            await log.show_thinking("已收到目标,思考中…")

        async def _produce() -> None:
            try:
                # 仅在真有图片附件时传 attachments kwarg → 无附件路径调用签名与改造前逐字一致
                # (测试/演示用的精简 fake loop 们无需都改 run 签名,零回归)。
                _run_kwargs = {"attachments": attachments} if attachments else {}
                async for ev in loop.run(goal, session_id=self._session_id, **_run_kwargs):
                    await bus.emit(ev)
            except Exception as e:  # noqa: BLE001 — loop 任何异常降级为 Error 事件
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
            log.finalize_response()
            self._run_active = False
            self._produce_worker = None
            self._glow_stop()
            try:
                self.query_one("#activity", ActivityPanel).on_run_end()
            except Exception:  # noqa: BLE001
                pass
            if self._interrupted:
                await log.append_line("⎋ 已打断当前任务。", kind="system")
                self._interrupted = False

    async def _start_run_daemon(self, goal: str, log, attachments: list | None = None) -> None:
        """daemon 路径(v6 P3b §3):POST /runs → DaemonEventSource 喂 EventBus。

        · Esc = POST cancel(已在 action_interrupt 处理)
        · Ctrl+B 后台化 = 断开 SSE 订阅即可(run 本来就在 daemon)
        · 审批决策:_handle_approval 走 POST /approval/{call_id}
        · plan 决策:_handle_plan_rendered 走 POST /plan_decision
        · 断线重连:DaemonEventSource 内置指数退避(最多 3 次)
        · 断连超阈值 → DaemonEventSource yield Error 事件,TUI 渲染后停止
        """
        from argos.tui.daemon_source import DaemonEventSource
        assert self._daemon_client is not None
        assert self._daemon_session_id is not None

        # 创建 run
        try:
            run_id = await self._daemon_client.create_run(
                self._daemon_session_id,
                goal=goal,
                workspace=str(self._workspace),
                approval_level="confirm",
                attachments=attachments or [],
            )
        except Exception as e:  # noqa: BLE001
            await log.append_line(f"◉ daemon create_run 失败:{e}", kind="error")
            self._run_active = False
            self._glow_stop()
            return

        self._daemon_run_id = run_id

        # 刷新 TabStrip
        self._refresh_tab_strip()

        await log.show_thinking("已收到目标,思考中…")

        # DaemonEventSource:SSE → typed Event 流
        socket_path = self._daemon_client.socket_path
        source = DaemonEventSource(
            socket_path, run_id, self._daemon_session_id,
        )
        bus = EventBus()

        async def _produce() -> None:
            try:
                async for ev in source.stream():
                    await bus.emit(ev)
            except asyncio.CancelledError:
                source.stop()
                raise
            except Exception as e:  # noqa: BLE001
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
            log.finalize_response()
            self._run_active = False
            self._produce_worker = None
            self._daemon_run_id = None
            self._glow_stop()
            try:
                self.query_one("#activity", ActivityPanel).on_run_end()
            except Exception:  # noqa: BLE001
                pass
            if self._interrupted:
                await log.append_line("⎋ 已打断当前任务。", kind="system")
                self._interrupted = False

    async def _announce_memory_recall(self, log, loop: object, goal: str) -> None:
        """記憶召回提示(spec §8.3 機會點⑤):v6 §4 ACP 後此方法已無操作。

        v6 P2:loop 在 run() 起始投 MemoryRecallEvent,TUI 在 _apply_event 消費渲染;
        TUI 不再主動訪問 loop._store(store 穿透修)。
        保留空方法避免移除觸發 call site 的 AttributeError。
        """

    async def _apply_event(self, ev: Event) -> None:
        """把一个契约 §1 Event 反映到对应 widget(一份事件三用的 UI 出口)。"""
        from argos.tui import glow
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
            # spec §8.4:新 plan 周期 = 全新一轮,解锁告警色(StatusBar -alert + 边框)。
            # 仅 plan 清——report/act/verify 绝不清(陷阱2:失败裁决的告警不被后续阶段抹掉)。
            if ev.phase == "plan" and self._terminal_glow:
                self._set_terminal_glow(False)
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
            ap.on_verdict(ev.verdict)   # 右栏 Verdict 区段(verify/idle 视图)同步
            # CONTRACT A:no_test==True = 仅因无 verify_cmd 而未机检,不是真实错误/篡改。
            # no_test 态用中性 idle 边框 + 不锁 StatusBar 告警色(绝不染橙/红)。
            # 只有"genuine unverifiable"(tamper/timeout/declared-but-failed) 才锁橙。
            _is_no_test = bool(getattr(ev.verdict, "no_test", False))
            if _is_no_test:
                # 中性收尾:边框回 idle,不锁 glow(诚实:没跑验证≠失败)
                from argos.tui import glow as _glow_mod
                self._set_border(_glow_mod.IDLE_BORDER)
                self._set_terminal_glow(False)
            else:
                # E4 防火墙:self_verified=True 的 passed 用 warning 橙而非 success 绿
                self._set_border(glow.verdict_color_self_aware(
                    ev.verdict.status,
                    self_verified=bool(getattr(ev.verdict, "self_verified", False)),
                ))
                if ev.verdict.status in ("failed", "unverifiable"):
                    # 锁定告警色(边框 + StatusBar -alert),后续 report 阶段色/眼不得覆盖(陷阱2)
                    # unverifiable 锁橙(真相不确定)而非红——三态语义纯度
                    self._set_terminal_glow(
                        True, kind="warn" if ev.verdict.status == "unverifiable" else "fail")
        elif isinstance(ev, CostUpdate):
            bar.set_cost(
                tokens_in=ev.tokens_in, tokens_out=ev.tokens_out,
                cost_usd=ev.cost_usd, elapsed_s=ev.elapsed_s,
            )
            ap.on_cost(
                tokens_in=ev.tokens_in, tokens_out=ev.tokens_out,
                cost_usd=ev.cost_usd, elapsed_s=ev.elapsed_s, cache_read=ev.cache_read,
                # #11 per-task routing:成本归属实际 profile(spec D15 短标签)。
                tier_name=ev.tier_name,
            )
            # 上下文占用%用【实际运行模型】的窗口当分母(active_tier),不能用模块级默认值——
            # 否则 active 是小窗口模型(如 Ollama 8192)时会拿 192000 当分母,谎报上下文压力。
            window = self._display_tier().context_window
            ap.on_context(used=ev.context_used, window=window)
        elif isinstance(ev, PlanUpdate):
            # 真 TODO 拆解 → 活动栏"任务进度"区改渲染子任务进度(Task 12)。
            ap.on_plan(ev.todos)
        elif isinstance(ev, CompactedEvent):
            # context rot 主动压缩(spec §8.1 机会点①):右栏上下文区追加 ↯ 压缩行 + transcript faint 系统行。
            # on_compacted 是 ActivityPanel 纯新增方法(陷阱1 except 模式由 query_one 外层保护)。
            try:
                ap.on_compacted(ev.before, ev.after, ev.reduction_pct)
            except Exception:  # noqa: BLE001 — 渲染失败不阻断 run
                pass
            pct = round(ev.reduction_pct * 100) if ev.reduction_pct <= 1 else round(ev.reduction_pct)
            await log.append_line(
                f"◌ 已压缩 -{pct}% · {ev.before}→{ev.after} 条", kind="system")
        elif isinstance(ev, PrunedEvent):
            # context rot 相关性修剪(spec §8.1 机会点①):右栏 + transcript faint 系统行。
            try:
                ap.on_pruned(ev.before, ev.after, ev.removed)
            except Exception:  # noqa: BLE001
                pass
            await log.append_line(f"◌ 已修剪 {ev.removed} 条", kind="system")
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
                f"◕ 工作流「{ev.name}」完成:{ev.synthesis}", kind="done")
        elif isinstance(ev, ToolReceipt):
            # 回执进活动栏面板的"回执"区 + 工具计数,不再进 transcript(Task 10)。
            # #6:把 HMAC 签名前 8 字符一并传入,让"已签名"成为可见、可证伪的事实而非空标签。
            ap.on_receipt(ev.receipt.action, ev.receipt.sig[:8])
        elif isinstance(ev, ApprovalRequest):
            await self._handle_approval(ev)
        elif isinstance(ev, PlanRendered):
            # Plan mode spec §2.5:loop 投 PlanRendered → TUI 推 PlanModal + 回调里把用户决策
            # 写回 loop._plan_decision + set event 唤醒 loop 的 await(见 _handle_plan_rendered)。
            await self._handle_plan_rendered(ev)
        elif isinstance(ev, PlanDecisionRequest):
            # v6 P3b §4:PlanDecisionRequest 携带 call_id,供 _handle_plan_rendered 路由。
            # 先记录 call_id;PlanRendered 紧随其后到达时 _handle_plan_rendered 取用。
            # inline 路径:loop.respond_plan_decision(call_id,...) 唤醒 loop。
            # daemon 路径:POST /plan_decision(call_id 由此携带,不再需要 ExitPlanMode)。
            self._current_plan_call_id = ev.call_id
        elif isinstance(ev, MemoryRecallEvent):
            # v6 §4 ACP:loop 投记忆召回事件,TUI 据此渲染"记忆召回 N 条"行。
            # 替换原来 _announce_memory_recall 对 loop._store 的直接访问(store 穿透修)。
            n = len(ev.hits)
            if n > 0:
                await log.append_line(f"◌ 记忆召回 {n} 条", kind="system")
                try:
                    ap.on_memory_recall(n)
                except Exception:  # noqa: BLE001 — 未 mount / 窄屏:静默
                    pass
        elif isinstance(ev, ApprovalResponse):
            await log.append_line(f"审批结果:{ev.call_id} → {ev.decision}")
        elif isinstance(ev, ProactiveSuggestionEvent):
            # P5b §9 自治面:conductor 建议到达 → transcript 只读展示 + 操作提示
            await self._on_proactive_suggestion(ev)
        elif isinstance(ev, ComputerActionEvent):
            # P6a §10 computer use:OS 级动作执行结果 → 活动栏一行人话
            await self._on_computer_action(ev)
        elif isinstance(ev, DreamProgressEvent):
            # T10 Dream 夜间整合进度 → DreamReportCard.append_stage（或回退 activity panel）
            dream_card = getattr(self, "_dream_card", None)
            if dream_card is not None:
                try:
                    dream_card.append_stage(ev.stage, ev.detail or "")
                except Exception:  # noqa: BLE001 — 静默
                    pass
            else:
                try:
                    detail = f" {ev.detail}" if ev.detail else ""
                    ap.append_line(f"[dream] {ev.stage}{detail}")
                except Exception:  # noqa: BLE001 — 未 mount / 静默
                    pass
        elif isinstance(ev, DreamReportEvent):
            # T10 Dream 整合结果汇总 → DreamReportCard.show_report（或回退 activity panel）
            dream_card = getattr(self, "_dream_card", None)
            if dream_card is not None:
                try:
                    dream_card.show_report({
                        "units_total": ev.units_total,
                        "promoted": ev.promoted,
                        "rejected": ev.rejected,
                        "skipped": ev.skipped,
                        "memory_merged": ev.memory_merged,
                        "memory_archived": ev.memory_archived,
                        "report_path": ev.report_path,
                    })
                except Exception:  # noqa: BLE001 — 静默
                    pass
            else:
                try:
                    summary_line = self._fmt_dream_report({
                        "units_total": ev.units_total,
                        "promoted": ev.promoted,
                        "rejected": ev.rejected,
                        "skipped": ev.skipped,
                        "memory_merged": ev.memory_merged,
                        "memory_archived": ev.memory_archived,
                    })
                    ap.append_line(summary_line)
                except Exception:  # noqa: BLE001 — 未 mount / 静默
                    pass
        elif isinstance(ev, Escalation):
            await log.append_line(f"⚠︎ 卡住({ev.attempts} 轮):{ev.reason} — 最后失败:{ev.last_failure}", kind="escalation")
            self._set_border(glow.ERROR)
            self._set_terminal_glow(True, kind="warn")   # escalation 锁橙(诚实喊人≠失败)(陷阱2)
        elif isinstance(ev, Error):
            chain = (" ← " + " ← ".join(ev.chain)) if ev.chain else ""
            await log.append_line(f"◉ 错误:{ev.message}{chain}", kind="error")
            self._set_border(glow.ERROR)
            self._set_terminal_glow(True)   # 告警锁色 + StatusBar -alert(陷阱2)

    def action_ctrl_c(self) -> None:
        """Ctrl+C:打断当前 run(同 Esc);idle 时 1.5s 内连按两次才退出。

        行为设计(对齐 Claude Code / Cursor / Aider 惯例):
          · 有 run 在跑 → 打断 run(同 action_interrupt);不退出
          · idle(无 run)且 1.5s 内第二次 → 退出(友好的双击退出,防误触)
          · idle 且首次 → transcript 提示"再按一次 Ctrl+C 退出",记录时间戳
        用户也可随时 Ctrl+D 确定性退出。
        """
        import time
        now = time.time()
        # 有 run 在跑 → 转发到打断逻辑(不退出)
        if self._run_active:
            self.action_interrupt()
            self._last_ctrl_c_time = 0.0  # 打断后重置退出计时
            return
        # idle:双击检测
        if (now - self._last_ctrl_c_time) < 1.5:
            self._last_ctrl_c_time = 0.0
            self.exit()
            return
        # 首次:提示
        self._last_ctrl_c_time = now
        try:
            self.run_worker(
                self.query_one("#transcript", Transcript).append_line(
                    "再按一次 Ctrl+C 退出(或 Ctrl+D 直接退出)。",
                    kind="system",
                ),
                exclusive=False,
            )
        except Exception:  # noqa: BLE001
            pass

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
                    f"› Run {self._daemon_run_id} 后台化(suspended)。可 /resume {self._daemon_run_id} 续。",
                    kind="system",
                ),
                exclusive=False,
            )
        except Exception:  # noqa: BLE001
            pass

    # ── TUI v2 行内选择:FIFO 队列(同屏最多一个活动 InlineChoice)──────────
    def _set_blocked_status(self, active: bool) -> None:
        """StatusBar 审批挂起态(spec §8.4 优先级铁律:用户阻塞 > 告警锁色 > 阶段眼)。

        任何 InlineChoice(工具/工作流/plan 审批)活动时置 True → 左眼强制 ◓ 金 + "审批挂起"段,
        即便引擎仍在 verify(右栏照常显 ❂)。队列全清后置 False。StatusBar 未 mount 时静默(陷阱1)。"""
        try:
            self.query_one("#status-bar", StatusBar).set_blocked(active)
        except Exception:  # noqa: BLE001 — 测试直构/未 mount:无副作用
            pass

    async def _enqueue_choice(self, factory: Callable[[], InlineChoice]) -> None:
        self._choice_queue.append(factory)
        if not self._choice_active:
            await self._mount_next_choice()

    async def _mount_next_choice(self) -> None:
        if not self._choice_queue:
            self._choice_active = False
            self._set_blocked_status(False)   # 队列空 = 无待审批 → 解除挂起态
            return
        self._choice_active = True
        self._set_blocked_status(True)        # 审批卡到达 → StatusBar 左眼 ◓ 审批挂起(优先级最高)
        widget = self._choice_queue.popleft()()
        await self.query_one("#transcript", Transcript).mount_block(widget)

    def _choice_done(self) -> None:
        """InlineChoice 决策落定 → 解锁并 mount 队列里的下一个(若有)。"""
        self._choice_active = False
        if self._choice_queue:
            self.run_worker(self._mount_next_choice(), exclusive=False)
        else:
            self._set_blocked_status(False)   # 最后一个决策落定 → 解除审批挂起态

    async def _handle_workflow_proposed(self, ev: WorkflowProposed) -> None:
        """工作流提议:① mount 进度树面板(存引用,后续 Progress/Done 据它刷新);
        ② 非 AUTO 档在流内 mount InlineChoice 显 preview,回调 gate.respond 放行 loop 的 await。
        AUTO 档下 loop 侧 gate.request 已自动放行、不真等 respond,故只 mount 面板、不渲染选择
        (渲染了也无 respond 对象,且 always 会多余)。"""
        log = self.query_one("#transcript", Transcript)
        panel = WorkflowPanel(name=ev.name)
        self._workflow_panel = panel
        await log.mount_block(panel)
        if self.gate.level is ApprovalLevel.AUTO:
            return  # loop 侧已自放行,不再渲染选择

        call_id = ev.call_id

        def _decide(value: str, _feedback: str) -> None:
            self.gate.respond(call_id, value)  # type: ignore[arg-type]
            self.run_worker(
                log.append_line(f"工作流审批:{ev.name} → {value}"),
                exclusive=False,
            )
            self._choice_done()

        await self._enqueue_choice(lambda: InlineChoice(
            title="工作流审批 — 将起多个子 agent 编排执行",
            body=ev.preview,
            options=[("once", "本次批准"), ("always", "总是批准"), ("deny", "拒绝")],
            on_decide=_decide,
            escape_value="deny",   # fail-closed:不明确批准即不放行
            risk="medium",
        ))

    def _on_gate_ask(self, call_id: str, payload: dict) -> None:
        """gate 进 ask 路径(broker 工具桥,call_id 为 gate 自生成)→ 构造 ApprovalRequest 并 mount
        审批卡。在 host_loop(Textual loop)线程上被同步调用(经 request_blocking 的
        run_coroutine_threadsafe),故用 run_worker 调度异步 _handle_approval。
        修 2026-06-18:此前 inline 模式 broker-gated 工具需审批时永远不弹卡、干等到超时。"""
        from argos.protocol.events import ApprovalRequest
        try:
            req = ApprovalRequest(
                call_id=call_id,
                action=str(payload.get("action", "")),
                args=payload.get("args", {}) or {},
                description=str(payload.get("description", "")),
                risk=payload.get("risk", "low"),
                trigger=str(payload.get("trigger", "")),
                secret_pattern=payload.get("secret_pattern"),
            )
            self.run_worker(self._handle_approval(req), exclusive=False)
        except Exception:  # noqa: BLE001 — mount 失败不得拖死 gate 的 ask
            pass

    async def _handle_approval(self, req: ApprovalRequest) -> None:
        """Auto 档不渲染直接 always;否则流内 mount InlineChoice(契约 §6.3),回调里 respond。

        v6 P3b §4:
          · daemon 模式 → InlineChoice 决定 → POST /runs/{id}/approval/{call_id}
          · inline 模式 → self.gate.respond(call_id, value)（原路径保留）
        """
        # computer.* 恒走硬确认:不受 AUTO/Trust Dial 降级(evaluator 已把金融域标 force-ask,
        # TUI 不得用 AUTO 短路把它 respond always 绕过)。非 computer.* 在 AUTO 下仍直接 always。
        if self.gate.level is ApprovalLevel.AUTO and not req.action.startswith("computer_"):
            if self._with_daemon and self._daemon_client and self._daemon_session_id and self._daemon_run_id:
                # daemon AUTO:直接 POST always(fire-and-forget)
                self.run_worker(
                    self._daemon_approval_post(req.call_id, "always"),
                    exclusive=False,
                )
            else:
                self.gate.respond(req.call_id, "always")
            return

        body_lines = [req.description, f"动作: {req.action} · 参数: {req.args}"]
        if getattr(req, "secret_pattern", None):
            body_lines.append("⚠︎ Possible secret pattern matched: did you mean to commit this?")

        _is_daemon = (
            self._with_daemon
            and self._daemon_client is not None
            and self._daemon_session_id is not None
            and self._daemon_run_id is not None
        )

        def _decide(value: str, _feedback: str) -> None:
            if _is_daemon:
                # daemon 路径:POST approval(async fire-and-forget from sync callback)
                self.run_worker(
                    self._daemon_approval_post(req.call_id, value),
                    exclusive=False,
                )
            else:
                # inline 路径:直接 resolve gate Future
                self.gate.respond(req.call_id, value)  # type: ignore[arg-type]
            self.run_worker(
                self.query_one("#transcript", Transcript).append_line(
                    f"审批结果:{req.action} → {value}"
                ),
                exclusive=False,
            )
            self._choice_done()

        if req.action.startswith("computer_"):
            await self._enqueue_choice(lambda: HardConfirmCard(
                action=req.action,
                x=req.args.get("x"),
                y=req.args.get("y"),
                description=req.description,
                on_decide=_decide,
                text=req.args.get("text"),
                app=req.args.get("app"),
            ))
            return

        await self._enqueue_choice(lambda: InlineChoice(
            title=format_approval_title(
                risk=req.risk, trigger=getattr(req, "trigger", "") or "",
            ),
            body="\n".join(body_lines),
            options=[
                ("once", "本次允许"), ("session", "本会话允许"),
                ("always", "总是允许"), ("deny", "拒绝"),
            ],
            on_decide=_decide,
            escape_value="deny",
            risk=req.risk,
        ))

    async def _daemon_approval_post(self, call_id: str, decision: str) -> None:
        """daemon 路径审批:POST /runs/{id}/approval/{call_id}。fail-soft(失败仅 log)。"""
        if not self._daemon_client or not self._daemon_session_id or not self._daemon_run_id:
            return
        try:
            await self._daemon_client.submit_approval(
                self._daemon_session_id, self._daemon_run_id, call_id, decision,
            )
        except Exception as e:  # noqa: BLE001
            import logging as _log
            _log.getLogger(__name__).warning("daemon approval POST failed: %s", e)

    async def _handle_plan_rendered(self, ev: "PlanRendered") -> None:
        """Plan mode spec §2.5:PlanRendered 事件 → 流内 InlineChoice(4 选项)→ 决策回传 loop。

        v6 P3b §4 统一路由:
          · daemon 模式 → POST /runs/{id}/plan_decision（call_id 来自 PlanDecisionRequest）
          · inline 模式 → loop.respond_plan_decision(call_id, action, feedback)
            彻底去掉 TUI 对 ExitPlanMode 的直接引用（设计 §4 刀2 收口）。

        plan_call_id 从 _current_plan_call_id 取（_apply_event 在 PlanDecisionRequest
        事件到达时设置；inline loop 须同时投 PlanRendered + PlanDecisionRequest 才能走此路）。
        无 call_id 时退到仅 inline loop.respond_plan_decision（向后兼容 FakeLoop 无 call_id）。
        """
        loop = self._current_loop

        if self.gate.level is ApprovalLevel.AUTO:
            # YOLO:不渲染，直接 approve_start
            call_id = getattr(self, "_current_plan_call_id", None)
            if self._with_daemon and self._daemon_client and self._daemon_session_id and self._daemon_run_id and call_id:
                self.run_worker(
                    self._daemon_plan_decision_post(call_id, "approve_start"),
                    exclusive=False,
                )
            elif loop is not None and hasattr(loop, "respond_plan_decision") and call_id:
                loop.respond_plan_decision(call_id, "approve_start", None)
            elif loop is not None:
                # 向后兼容:FakeLoop / 旧 loop 无 call_id → ExitPlanMode
                from argos.core.plan_mode import ExitPlanMode
                ExitPlanMode(loop, "approve_start")
            return

        if loop is None and not (self._with_daemon and self._daemon_run_id):
            return  # run 已结束

        _is_daemon = (
            self._with_daemon
            and self._daemon_client is not None
            and self._daemon_session_id is not None
            and self._daemon_run_id is not None
        )

        def _decide(value: str, feedback: str) -> None:
            call_id = getattr(self, "_current_plan_call_id", None)
            if _is_daemon and call_id:
                self.run_worker(
                    self._daemon_plan_decision_post(call_id, value, feedback if value == "refine" else None),
                    exclusive=False,
                )
            elif loop is not None and hasattr(loop, "respond_plan_decision") and call_id:
                loop.respond_plan_decision(call_id, value, feedback if value == "refine" else None)
            elif loop is not None:
                # 向后兼容(FakeLoop / 旧 loop 无 call_id)
                from argos.core.plan_mode import ExitPlanMode
                ExitPlanMode(loop, value, feedback if value == "refine" else None)
            self.run_worker(
                self.query_one("#transcript", Transcript).append_line(
                    f"Plan 决策:{value}", kind="system"
                ),
                exclusive=False,
            )
            self._choice_done()

        await self._enqueue_choice(lambda: InlineChoice(
            title="◓ 计划已就绪 — 如何继续?",
            body=ev.plan_md,
            options=[
                ("approve_start", "批准,开始执行"),
                ("approve_accept_edits", "批准 + 自动接受编辑"),
                ("keep_planning", "继续规划"),
                ("refine", "补充反馈后再规划"),
            ],
            on_decide=_decide,
            escape_value=None,
            needs_input={"refine"},
            input_placeholder="补充对 plan 的反馈,Enter 提交,Esc 返回",
            risk="plan",
        ))

    async def _daemon_plan_decision_post(self, call_id: str, action: str, feedback: str | None = None) -> None:
        """daemon 路径 plan 决策:POST /runs/{id}/plan_decision。fail-soft(失败仅 log)。"""
        if not self._daemon_client or not self._daemon_session_id or not self._daemon_run_id:
            return
        try:
            body = {"call_id": call_id, "action": action}
            if feedback:
                body["feedback"] = feedback
            await self._daemon_client._request(
                "POST",
                f"/runs/{self._daemon_run_id}/plan_decision",
                session_id=self._daemon_session_id,
                body=body,
            )
        except Exception as e:  # noqa: BLE001
            import logging as _log
            _log.getLogger(__name__).warning("daemon plan_decision POST failed: %s", e)
