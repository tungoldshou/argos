"""Textual client for Argos interactive runs.

Source-doc contract:
- compare <task_id>[:<model>] <task_id>[:<model>]
- command config files live at ARGOS_CONFIG_DIR/hooks.json, ARGOS_CONFIG_DIR/lsp.json,
  ARGOS_CONFIG_DIR/permissions.json, and ARGOS_CONFIG_DIR/mcp.json.
"""
from __future__ import annotations

import re
import uuid
from collections import deque
from collections.abc import Callable
from pathlib import Path

from textual import events
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal

from argos import config
from argos.approval import ApprovalGate, ApprovalLevel, derive_persistent_allow_rule
from argos.core.snapshot import SNAPSHOT_ROOT, RunSnapshot
from argos.hooks.events import HookFired
from argos.tui.commands import SlashCommand, match_commands, parse_slash
from argos.tui.events import (
    ApprovalRequest,
    ApprovalResponse,
    CodeAction,
    CodeResult,
    CompactedEvent,
    ComputerActionEvent,
    DreamProgressEvent,
    DreamReportEvent,
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
    ProactiveSuggestionEvent,
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
from argos.input.clipboard_image import read_clipboard_image, ClipboardError
from argos.tui.widgets.workflow_panel import WorkflowPanel
from argos.i18n import t

_BASE_SUBTITLE = t("tui.app.subtitle")


def _app_version() -> str:
    try:
        from argos import __version__
        return __version__
    except Exception:  # noqa: BLE001
        return "0.x"


def _argos_dir() -> Path:
    return config.config_dir()


class ArgosApp(App):
    TITLE = "Argos"

    #
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
    #prompt:focus { border-top: solid $eye; }
    ArgosApp.-narrow #activity { display: none; }
    """

    HORIZONTAL_BREAKPOINTS = [(0, "-narrow"), (90, "-wide")]

    AUTO_FOCUS = "#prompt"

    BINDINGS = [
        Binding("pageup", "transcript_page_up", show=False, priority=True),
        Binding("pagedown", "transcript_page_down", show=False, priority=True),
        ("ctrl+c", "ctrl_c", t("tui.bind.interrupt_quit")),
        ("ctrl+d", "quit", t("tui.bind.quit")),
        ("escape", "interrupt", t("tui.bind.interrupt")),
        ("ctrl+b", "background", t("tui.bind.background")),
        ("ctrl+o", "cycle_panel", t("tui.bind.right_panel")),
        ("ctrl+v", "paste_image", t("tui.bind.paste_image")),
    ]

    def __init__(
        self, *, loop_factory: Callable[[], object] | None = None,
        gate: ApprovalGate | None = None,
        workspace: Path | str | None = None,
    ) -> None:
        super().__init__()
        self._workspace_override: Path | None = (
            Path(workspace).expanduser().resolve() if workspace else None
        )
        self.register_theme(ARGOS_NIGHT)
        self.theme = "argos-night"
        self._loop_factory = loop_factory or (lambda **kw: FakeLoop())
        self.gate = gate or ApprovalGate(ApprovalLevel.CONFIRM)
        self._step_blocks: dict[int, CodeActionBlock] = {}
        self._workflow_panel: WorkflowPanel | None = None
        self._run_active = False
        self._produce_worker = None
        self._interrupted = False
        self._yolo = False
        self._current_loop: object | None = None
        self._plan_mode = False
        self._session_id = uuid.uuid4().hex
        self._workspace: Path = self._workspace_override or (_argos_dir() / "workspace")
        self._run_seq: int = 0
        self._snapshot: "RunSnapshot | None" = None
        self._kernel_mode: str = ""
        self._with_daemon: bool = False
        self._daemon_client = None     # type: ignore[var-annotated]
        self._daemon_session_id: str | None = None
        self._daemon_run_id: str | None = None
        self._daemon_hb_timer = None
        self._conductor_source = None            # DaemonEventSource for _conductor SSE stream
        self._last_esc_time: float = 0.0
        self._last_ctrl_c_time: float = 0.0
        self._input_history: list[str] = []
        self._input_history_max: int = 50
        self._choice_active = False
        self._choice_queue: deque[Callable[[], InlineChoice]] = deque()
        self._current_plan_call_id: str | None = None
        self.sub_title = self._compose_subtitle()

    @staticmethod
    def _display_tier():
        from argos import config
        try:
            return config.active_tier()
        except Exception:  # noqa: BLE001
            return config.DEFAULT_TIER

    def _compose_subtitle(self) -> str:
        parts = [_BASE_SUBTITLE]
        if self._plan_mode:
            parts.append("· [plan mode]")
        if self._yolo:
            parts.append("· ⏻ YOLO(Auto)")
        return "  ".join(parts)

    def _resolve_trust_level(self):
        from argos.permissions.trust_dial import TrustLevel
        _map = {
            ApprovalLevel.CONFIRM:      TrustLevel.L1_DANGEROUS_ONLY,
            ApprovalLevel.ACCEPT_EDITS: TrustLevel.L3_SESSION_TRUSTED,
            ApprovalLevel.AUTO:         TrustLevel.L4_AUTONOMOUS,
            ApprovalLevel.OBSERVE:      TrustLevel.L0_EVERY_STEP,
            ApprovalLevel.PROPOSE:      TrustLevel.L0_EVERY_STEP,
        }
        current = _map.get(self.gate.level, TrustLevel.L1_DANGEROUS_ONLY)
        if getattr(self.gate, "_ask_readonly", False):
            current = TrustLevel.L0_EVERY_STEP
        stored = getattr(self.gate, "_trust_level", None)
        if isinstance(stored, TrustLevel):
            current = stored
        return current

    def _refresh_topbar(self) -> None:
        try:
            tl = self._resolve_trust_level()
            self.query_one("#top-bar", TopBar).set_state(
                plan_mode=self._plan_mode, yolo=self._yolo,
                has_key=bool(config.active_key()),
                trust_level=int(tl), trust_label=tl.label_human,
            )
        except Exception:  # noqa: BLE001
            pass

    async def action_paste_image(self) -> None:
        try:
            att = read_clipboard_image()
        except ClipboardError as e:
            self.run_worker(
                self.query_one("#transcript", Transcript).append_line(
                    t("tui.paste.failed", err=e), kind="error",
                ),
                exclusive=False,
            )
            return
        try:
            prompt = self.query_one("#prompt", PromptArea)
        except Exception:  # noqa: BLE001
            return
        token = prompt.register_image(att)
        prompt.insert(token)

    def action_cycle_panel(self) -> None:
        try:
            self.query_one("#activity", ActivityPanel).cycle_view()
        except Exception:  # noqa: BLE001
            pass

    def _scroll_transcript(self, method: str) -> None:
        try:
            getattr(self.query_one("#transcript", Transcript), method)(animate=False)
        except Exception:  # noqa: BLE001
            pass

    def _wheel_transcript(self, event: events.MouseEvent, method: str) -> None:
        self._scroll_transcript(method)
        event.stop()

    def action_transcript_page_up(self) -> None:
        self._scroll_transcript("scroll_page_up")

    def action_transcript_page_down(self) -> None:
        self._scroll_transcript("scroll_page_down")

    def _on_mouse_scroll_up(self, event: events.MouseScrollUp) -> None:
        self._wheel_transcript(event, "scroll_up")

    def _on_mouse_scroll_down(self, event: events.MouseScrollDown) -> None:
        self._wheel_transcript(event, "scroll_down")

    def compose(self) -> ComposeResult:
        tier = self._display_tier()
        yield TopBar(version=_app_version(), model_label=tier.model, id="top-bar")
        yield TabStrip(id="tab-strip")
        with Horizontal():
            yield Transcript(id="transcript")
            yield ActivityPanel(id="activity", model_label=tier.model, tier=tier.name)
        yield StatusBar(id="status-bar")
        yield SlashMenu(id="slash-menu")
        yield PromptArea(placeholder=t("tui.prompt.placeholder"), id="prompt")

    def on_mount(self) -> None:
        self._refresh_topbar()
        self.query_one("#prompt", PromptArea).focus()
        tier = self._display_tier()
        has_key = False
        key_config_error = None
        try:
            has_key = bool(config.active_key())
        except config.ConfigError as e:
            key_config_error = str(e)
        splash = StartupSplash(
            model_label=tier.model, tier=tier.name,
            live=True, has_key=has_key,
        )
        if key_config_error:
            splash.set_bad_config(key_config_error, source="config")
        self.query_one("#transcript", Transcript).mount(splash)
        self._set_plan_mode_indicators()
        self._terminal_glow = False
        self._glow_base = None
        self._glow_phase = 0.0
        self._glow_timer = None
        try:
            from argos.hooks import reload_config
            reload_config()
        except Exception as e:  # noqa: BLE001
            for sp in self.query(StartupSplash):
                sp.set_bad_config(str(e))
        try:
            from argos.lsp import reload_config as _lsp_reload_config
            _lsp_reload_config()
        except Exception as e:  # noqa: BLE001
            for sp in self.query(StartupSplash):
                sp.set_bad_config(f"LSP {e}")
        try:
            from argos.permissions import reload_config as _perm_reload_config
            _perm_reload_config()
        except Exception as e:  # noqa: BLE001
            for sp in self.query(StartupSplash):
                sp.set_bad_config(f"permissions: {e}")
        try:
            ap = self.query_one("#activity", ActivityPanel)
            self.gate.set_decision_listener(
                lambda action, decision, trigger: ap.on_approval_decision(
                    action=action, decision=decision, trigger=trigger,
                )
            )
        except Exception:  # noqa: BLE001
            pass
        try:
            self.gate.set_ask_listener(self._on_gate_ask)
        except Exception:  # noqa: BLE001
            pass
        try:
            self.gate.set_workspace(str(self._workspace))
        except Exception:  # noqa: BLE001
            pass
        if self._daemon_client is None:
            self.run_worker(self._setup_daemon_mode(), exclusive=False)

    async def _setup_daemon_mode(self) -> None:
        import os
        from argos import config as _cfg
        from argos.tui.daemon_spawn import probe_or_spawn
        from argos.daemon.client import DaemonClient

        if os.environ.get("ARGOS_NO_DAEMON") == "1":
            self._kernel_mode = "inline"
            self._with_daemon = False
            try:
                self.query_one("#status-bar", StatusBar).set_kernel_mode(t("tui.kernel.inline"))
            except Exception:  # noqa: BLE001
                pass
            return

        socket_path = Path(_cfg.get("ARGOS_DAEMON_SOCKET") or (_argos_dir() / "daemon.sock")).expanduser()

        ready = await probe_or_spawn(socket_path)
        if not ready:
            self._kernel_mode = "inline"
            self._with_daemon = False
            try:
                self.query_one("#status-bar", StatusBar).set_kernel_mode(t("tui.kernel.inline"))
            except Exception:  # noqa: BLE001
                pass
            try:
                self.run_worker(
                    self.query_one("#transcript", Transcript).append_line(
                        t("tui.daemon.unavailable"),
                        kind="error",
                    ),
                    exclusive=False,
                )
            except Exception:  # noqa: BLE001
                pass
            return

        client = DaemonClient(socket_path)
        try:
            sid = await client.create_session()
        except Exception as e:  # noqa: BLE001
            import logging as _log
            _log.getLogger(__name__).warning("daemon session create failed: %s", e)
            self._kernel_mode = "inline"
            self._with_daemon = False
            try:
                self.query_one("#status-bar", StatusBar).set_kernel_mode(t("tui.kernel.inline"))
            except Exception:  # noqa: BLE001
                pass
            try:
                self.run_worker(
                    self.query_one("#transcript", Transcript).append_line(
                        t("tui.daemon.unavailable"),
                        kind="error",
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
        self._start_daemon_heartbeat()
        # ponytail: one worker, torn down by source.stop() on disconnect / app exit.
        self._start_conductor_subscription(socket_path, sid)

    _DAEMON_HB_INTERVAL_S: float = 10.0

    def _start_daemon_heartbeat(self) -> None:
        if self._daemon_hb_timer is not None:
            return
        try:
            self._daemon_hb_timer = self.set_interval(
                self._DAEMON_HB_INTERVAL_S, self._daemon_heartbeat_tick
            )
        except Exception:  # noqa: BLE001
            self._daemon_hb_timer = None

    async def _daemon_heartbeat_tick(self) -> None:
        if not self._with_daemon or self._daemon_client is None or self._daemon_session_id is None:
            return
        from argos.daemon.client import DaemonError
        from argos.daemon.protocol import CODE_MISSING_SESSION
        try:
            await self._daemon_client.heartbeat(self._daemon_session_id)
        except DaemonError as e:
            if e.code == CODE_MISSING_SESSION:
                try:
                    self._daemon_session_id = await self._daemon_client.create_session()
                except Exception:  # noqa: BLE001
                    pass
        except Exception:  # noqa: BLE001
            pass


    def _start_conductor_subscription(self, socket_path: "Path", session_id: str) -> None:
        from argos.tui.daemon_source import DaemonEventSource

        if self._conductor_source is not None:
            return

        source = DaemonEventSource(socket_path, "_conductor", session_id)
        self._conductor_source = source

        async def _stream_conductor() -> None:
            try:
                async for ev in source.stream():
                    try:
                        await self._apply_event(ev)
                    except Exception:  # noqa: BLE001
                        pass
            except Exception:  # noqa: BLE001
                pass
            finally:
                source.stop()
                self._conductor_source = None

        self.run_worker(_stream_conductor, exclusive=False)

    async def _daemon_create_run(
        self, goal: str, attachments: list | None, *, verify_cmd: str | None = None
    ) -> str:
        from argos.daemon.client import DaemonError
        from argos.daemon.protocol import CODE_MISSING_SESSION
        assert self._daemon_client is not None
        assert self._daemon_session_id is not None
        try:
            return await self._daemon_client.create_run(
                self._daemon_session_id, goal=goal,
                workspace=str(self._workspace), approval_level="confirm",
                attachments=attachments or [], verify_cmd=verify_cmd,
            )
        except DaemonError as e:
            if e.code != CODE_MISSING_SESSION:
                raise
            self._daemon_session_id = await self._daemon_client.create_session()
            return await self._daemon_client.create_run(
                self._daemon_session_id, goal=goal,
                workspace=str(self._workspace), approval_level="confirm",
                attachments=attachments or [], verify_cmd=verify_cmd,
            )

    def _set_border(self, color) -> None:
        self.screen.styles.border = ("round", color)

    def _set_terminal_glow(self, active: bool, *, kind: str = "fail") -> None:
        self._terminal_glow = active
        try:
            self.query_one("#status-bar", StatusBar).set_alert(active, kind=kind)
        except Exception:  # noqa: BLE001
            pass

    def _glow_start(self) -> None:
        from argos.tui import glow
        self._set_terminal_glow(False)
        self._glow_phase = 0.0
        self._glow_base = glow.phase_color("plan")
        self._set_border(self._glow_base)
        if self._glow_timer is None:
            self._glow_timer = self.set_interval(0.1, self._glow_breathe)

    def _glow_breathe(self) -> None:
        from argos.tui import glow
        if self._terminal_glow or self._glow_base is None:
            return
        self._glow_phase = (self._glow_phase + 0.03) % 1.0
        self._set_border(glow.breathe(self._glow_base, self._glow_phase))

    def _glow_stop(self) -> None:
        from argos.tui import glow
        if self._glow_timer is not None:
            self._glow_timer.stop()
            self._glow_timer = None
        self._glow_base = None
        self._set_border(glow.IDLE_BORDER)

    def _set_plan_mode_indicators(self) -> None:
        from argos.tui import glow
        for sp in self.query(StartupSplash):
            sp.set_plan_mode(self._plan_mode)
        try:
            self.query_one("#status-bar", StatusBar).set_plan_mode(self._plan_mode)
        except Exception:  # noqa: BLE001
            pass
        self.sub_title = self._compose_subtitle()
        self._refresh_topbar()
        if self._plan_mode and not self._run_active:
            self._set_border(glow.phase_color("plan"))

    def on_prompt_area_submitted(self, event: PromptArea.Submitted) -> None:
        self.query_one("#slash-menu", SlashMenu).hide()
        self.handle_input(event.text, event.attachments)

    def on_tab_strip_tab_activated(self, event: TabActivated) -> None:
        self.run_worker(self._on_tab_activated(event.run_id), exclusive=False)

    async def _on_tab_activated(self, run_id: str) -> None:
        if not self._with_daemon or not self._daemon_client or not self._daemon_session_id:
            return
        try:
            status, _, raw = await self._daemon_client._request(
                "POST", f"/runs/{run_id}/focus", session_id=self._daemon_session_id,
            )
            if status != 200:
                raise RuntimeError(f"HTTP {status}: {raw.decode('utf-8', errors='replace')}")
        except Exception as e:  # noqa: BLE001
            try:
                log_widget = self.query_one(Transcript)
                await log_widget.append_line(
                    t("tui.tab.focus_failed", id=run_id[:8], err=e), kind="error",
                )
            except Exception:  # noqa: BLE001
                pass
            return
        self._daemon_run_id = run_id
        try:
            strip = self.query_one(TabStrip)
            strip.set_active(run_id)
        except Exception:  # noqa: BLE001
            pass
        self._last_esc_time = 0.0
        self.run_worker(self._replay_run_to_transcript(run_id), exclusive=False)

    async def _replay_run_to_transcript(self, run_id: str) -> None:
        try:
            log_widget = self.query_one(Transcript)
            await log_widget.append_line(
                t("tui.tab.switched", id=run_id[:8]), kind="system",
            )
        except Exception:  # noqa: BLE001
            pass

    def _refresh_tab_strip(self) -> None:
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
        menu = self.query_one("#slash-menu", SlashMenu)
        menu.show_matches(match_commands(event.text_area.text))

    def _push_input_history(self, text: str) -> None:
        t = text.strip()
        if not t:
            return
        if self._input_history and self._input_history[-1] == t:
            return
        self._input_history.append(t)
        if len(self._input_history) > self._input_history_max:
            self._input_history.pop(0)

    def handle_input(self, text: str, attachments: list | None = None) -> None:
        if text.strip():
            self._push_input_history(text)
        cmd = parse_slash(text)
        if cmd is None:
            if text.strip():
                if self._run_active:
                    self.run_worker(
                        self.query_one("#transcript", Transcript).append_line(
                            t("tui.run.busy")
                        ),
                        exclusive=False,
                    )
                    return
                self.run_worker(self.start_run(text.strip(), attachments or []), exclusive=False)
            return
        self.run_worker(self._dispatch_slash(cmd), exclusive=False)

    @staticmethod
    def _slash_handlers() -> dict[str, str]:
        """Slash command dispatch table.

        Values are ArgosApp method names with signature (log, arg).
        """
        return {
            "yolo": "_cmd_yolo",
            "trust": "_trust_cmd",
            "model": "_cmd_model",
            "status": "_cmd_status",
            "cost": "_cmd_cost",
            "clear": "_cmd_clear",
            "resume": "_cmd_resume",
            "help": "_cmd_help",
            "voice": "_cmd_voice",
            "tools": "_cmd_tools",
            "skills": "_cmd_skills",
            "mcp": "_cmd_mcp",
            "undo": "_cmd_undo",
            "ledger": "_cmd_ledger",
            "journal": "_journal_cmd",
            "setup": "_cmd_setup",
            "retry": "_cmd_retry",
            "plan": "_cmd_plan",
            "hooks": "_hooks_cmd",
            "lsp": "_lsp_cmd",
            "permissions": "_permissions_cmd",
            "runs": "_runs_cmd",
            "orders": "_cmd_orders",
            "confirm": "_confirm_suggestion_cmd",
            "dismiss": "_dismiss_suggestion_cmd",
            "verify": "_cmd_verify",
            "security-review": "_cmd_security_review",
            "simplify": "_cmd_simplify",
            "remember": "_remember_cmd",
            "forget": "_forget_cmd",
            "memory": "_cmd_memory",
            "eval": "_eval_cmd",
            "routing": "_routing_cmd",
            "context": "_context_cmd",
            "dream": "_dream_cmd",
            "goal": "_cmd_goal",
            "loop": "_cmd_loop",
            "schedule": "_schedule_cmd",
            "watch": "_watch_cmd",
        }

    async def _cmd_yolo(self, log, arg: str) -> None:
        if arg.strip():
            await log.append_line(t("tui.yolo.usage"), kind="error")
            return
        self.gate.set_trust_level(
            __import__("argos.permissions.trust_dial", fromlist=["TrustLevel"]).TrustLevel.L4_AUTONOMOUS
        )
        self._yolo = True
        self.sub_title = self._compose_subtitle()
        self._refresh_topbar()
        await log.append_line(t("tui.yolo.activated"))

    async def _cmd_model(self, log, arg: str) -> None:
        import os
        from argos import config as _cfg
        if not arg:
            try:
                if _cfg._has_config_file():
                    cfg = _cfg.load_config()
                    profs = list(cfg.tiers)
                    cur = cfg.active
                    labels = []
                    for p in profs:
                        env_name = cfg.key_envs.get(p, "")
                        suffix = " *" if p == cur else ""
                        if env_name and not (os.environ.get(env_name) or cfg.secrets.get(env_name)):
                            suffix += f" {t('tui.model.missing_key_short', env=env_name)}"
                        labels.append(f"{p}{suffix}")
                else:
                    profs = _cfg.list_profiles()
                    labels = [f"{p}{' *' if i == 0 else ''}" for i, p in enumerate(profs)]
            except Exception as e:  # noqa: BLE001
                await log.append_line(t("tui.model.switch_failed", err=e), kind="error")
                return
            await log.append_line(
                t("tui.model.available", list=", ".join(labels)),
                kind="system")
            return
        try:
            cfg = _cfg.load_config()
            if arg in cfg.key_envs and _cfg.key_for(arg) is None:
                raise _cfg.ConfigError(t(
                    "tui.model.missing_key",
                    name=arg,
                    env=cfg.key_envs.get(arg) or "(none)",
                ))
            _cfg.set_active(arg)
            await log.append_line(t("tui.model.switched", name=arg), kind="done")
        except Exception as e:  # noqa: BLE001
            await log.append_line(t("tui.model.switch_failed", err=e), kind="error")

    async def _cmd_status(self, log, arg: str) -> None:
        if arg.strip():
            await log.append_line(t("tui.status.usage"), kind="error")
            return
        bar = self.query_one("#status-bar", StatusBar)
        await log.append_line(bar.render_text)

    async def _cmd_cost(self, log, arg: str) -> None:
        if arg.strip():
            await log.append_line(t("tui.cost.usage"), kind="error")
            return
        ap = self.query_one("#activity", ActivityPanel)
        await log.append_line(t("tui.cost.header") + "\n" + ap.snapshot_text())

    async def _cmd_clear(self, log, arg: str) -> None:
        if arg.strip():
            await log.append_line(t("tui.clear.usage"), kind="error")
            return
        await log.clear()
        self._step_blocks.clear()
        self._session_id = uuid.uuid4().hex
        await log.append_line(t("tui.clear.done"))

    async def _cmd_resume(self, log, arg: str) -> None:
        if arg.strip():
            await log.append_line(t("tui.resume.usage"), kind="error")
            return
        await self._resume_recent(log)

    async def _cmd_help(self, log, arg: str) -> None:
        from argos.tui.commands import ADVANCED_COMMAND_NAMES, DEFAULT_COMMAND_NAMES, _build_command_help
        _ch = _build_command_help()
        name = arg.strip().lstrip("/").lower()
        if name == "advanced":
            advanced = _build_command_help(ADVANCED_COMMAND_NAMES)
            lines = [t("tui.help.advanced_header")]
            lines += [f" · /{cmd:<16} {desc}" for cmd, desc in advanced.items()]
            await log.append_line("\n".join(lines), kind="system")
            return
        if name:
            hidden = {
                "remember": t("tui.remember.usage"),
                "forget": t("tui.forget.usage"),
                "memory": t("tui.memory.usage"),
            }
            desc = _ch.get(name) or hidden.get(name)
            if desc is None:
                await log.append_line(t("tui.help.usage", name=name), kind="error")
                return
            await log.append_line(f"/{name}  {desc}", kind="system")
            return
        core = _build_command_help(DEFAULT_COMMAND_NAMES)
        lines = [t("tui.help.header")]
        lines += [f" · /{cmd:<16} {desc}" for cmd, desc in core.items()]
        lines.append(t("tui.help.advanced_hint"))
        lines.append(t("tui.help.shortcuts"))
        await log.append_line("\n".join(lines), kind="system")

    async def _cmd_tools(self, log, arg: str) -> None:
        if arg.strip():
            await log.append_line(t("tui.tools.usage"), kind="error")
            return
        await self._show_tools(log)

    async def _cmd_skills(self, log, arg: str) -> None:
        self._last_skills_arg = arg
        await self._show_skills(log)

    async def _cmd_mcp(self, log, arg: str) -> None:
        if arg.strip():
            await log.append_line(t("tui.mcp.usage"), kind="error")
            return
        await self._show_mcp(log)

    async def _cmd_undo(self, log, arg: str) -> None:
        if arg.strip():
            await log.append_line(t("tui.undo.usage"), kind="error")
            return
        await self._undo(log)

    async def _cmd_ledger(self, log, arg: str) -> None:
        if arg.strip():
            await log.append_line(t("tui.ledger.usage"), kind="error")
            return
        await self._ledger_cmd(log)

    async def _cmd_setup(self, log, arg: str) -> None:
        if arg.strip():
            await log.append_line(t("tui.setup.usage"), kind="error")
            return
        await self._setup_cmd(log)

    async def _cmd_retry(self, log, arg: str) -> None:
        if arg.strip():
            await log.append_line(t("tui.retry.usage"), kind="error")
            return
        await self._retry(log)

    async def _cmd_plan(self, log, arg: str) -> None:
        if arg.strip():
            await log.append_line(t("tui.plan.usage"), kind="error")
            return
        await self._enter_plan_mode(log)

    async def _cmd_orders(self, log, arg: str) -> None:
        if arg.strip():
            await log.append_line(t("tui.orders.usage"), kind="error")
            return
        await self._orders_cmd(log)

    async def _cmd_verify(self, log, arg: str) -> None:
        await self._skill_cmd(log, "verify", arg)

    async def _cmd_security_review(self, log, arg: str) -> None:
        await self._skill_cmd(log, "security-review", arg)

    async def _cmd_simplify(self, log, arg: str) -> None:
        await self._skill_cmd(log, "simplify", arg)

    async def _cmd_memory(self, log, arg: str) -> None:
        if arg.strip():
            await log.append_line(t("tui.memory.usage"), kind="error")
            return
        await self._memory_cmd(log)

    async def _cmd_goal(self, log, arg: str) -> None:
        await self._goal_cmd(log, "goal", arg)

    async def _cmd_loop(self, log, arg: str) -> None:
        await self._goal_cmd(log, "loop", arg)

    async def _dispatch_slash(self, cmd: SlashCommand) -> None:
        log = self.query_one("#transcript", Transcript)
        if not cmd.known:
            await log.append_line(t("tui.cmd.unknown", name=cmd.name), kind="error")
            return
        method_name = self._slash_handlers().get(cmd.name)
        if method_name is None:
            await log.append_line(t("tui.cmd.unwired", name=cmd.name), kind="error")
            return
        await getattr(self, method_name)(log, cmd.arg)

    async def _undo(self, log) -> None:
        if self._snapshot is None or not self._snapshot.tar_path.exists():
            await log.append_line(t("tui.undo.no_snapshot"), kind="system")
            return
        result = self._snapshot.restore(self._workspace)
        try:
            from argos.memory import auto as _mem_auto
            from argos.memory.auto import project_id_for as _pid
            reason = "snapshot restored" if not result.errors else f"partial restore ({len(result.errors)} errors)"
            _mem_auto.capture_event("undo", project_id=_pid(self._workspace), reason=reason)
        except Exception:  # noqa: BLE001
            pass
        if result.errors:
            head = "\n".join(f"  ✗ {p}: {e}" for p, e in result.errors[:5])
            more = t("tui.undo.more") if len(result.errors) > 5 else ""
            await log.append_line(
                t("tui.undo.partial", ok=len(result.restored), fail=len(result.errors), head=head, more=more),
                kind="error",
            )
        else:
            await log.append_line(
                t("tui.undo.success", n=len(result.restored)),
                kind="done",
            )

    async def _trust_cmd(self, log, arg: str) -> None:
        from argos.permissions.trust_dial import (
            TrustLevel, escalation_warning, next_in_cycle, to_approval_semantics,
        )
        arg = arg.strip().lower()

        current_trust = self._resolve_trust_level()

        if arg in ("status", "s"):
            await log.append_line(
                t("tui.trust.status", mode_name=current_trust.mode_name, label_human=current_trust.label_human, description=current_trust.description),
                kind="system",
            )
            await log.mount_block(TrustDial(current=current_trust))
            return

        if not arg:
            target_trust = next_in_cycle(current_trust)
        else:
            _arg_map: dict[str, TrustLevel] = {
                "cautious": TrustLevel.L1_DANGEROUS_ONLY,
                "trusted": TrustLevel.L3_SESSION_TRUSTED,
                "autonomous": TrustLevel.L4_AUTONOMOUS,
                "auto": TrustLevel.L4_AUTONOMOUS,
                "paranoid": TrustLevel.L0_EVERY_STEP,
                "l0": TrustLevel.L0_EVERY_STEP,
                "l1": TrustLevel.L1_DANGEROUS_ONLY,
                "l2": TrustLevel.L2_IRREVERSIBLE_ONLY,
                "l3": TrustLevel.L3_SESSION_TRUSTED,
                "l4": TrustLevel.L4_AUTONOMOUS,
            }
            target_trust = _arg_map.get(arg)
            if target_trust is None:
                await log.append_line(
                    t("tui.trust.unknown_mode", arg=arg),
                    kind="error",
                )
                return

        if target_trust is current_trust:
            await log.append_line(
                t("tui.trust.already", mode_name=target_trust.mode_name, label_human=target_trust.label_human),
                kind="system",
            )
            return

        if int(target_trust) < int(current_trust):
            self.gate.set_trust_level(target_trust)
            self._yolo = (target_trust is TrustLevel.L4_AUTONOMOUS)
            self.sub_title = self._compose_subtitle()
            self._refresh_topbar()
            await log.append_line(
                t("tui.trust.downgraded", mode_name=target_trust.mode_name, label_human=target_trust.label_human),
                kind="done",
            )
            return

        warning_text = escalation_warning(current_trust, target_trust)
        target_name = target_trust.mode_name
        target_label = target_trust.label_human

        def _on_trust_confirm(value: str, _feedback: str) -> None:
            if value == "confirm":
                self.gate.set_trust_level(target_trust)
                self._yolo = (target_trust is TrustLevel.L4_AUTONOMOUS)
                self.sub_title = self._compose_subtitle()
                self._refresh_topbar()
                _yolo_note = t("tui.trust.yolo_note") if target_trust is TrustLevel.L4_AUTONOMOUS else ""
                self.run_worker(
                    log.append_line(
                        t("tui.trust.upgraded", mode_name=target_name, label_human=target_label, yolo_note=_yolo_note),
                        kind="done",
                    ),
                    exclusive=False,
                )
            else:
                self.run_worker(
                    log.append_line(t("tui.trust.cancelled"), kind="system"),
                    exclusive=False,
                )
            self._choice_done()

        await self._enqueue_choice(lambda: InlineChoice(
            title=t("tui.trust.confirm_title", label_human=target_label),
            body=warning_text,
            options=[("confirm", t("tui.trust.confirm_yes")), ("cancel", t("tui.trust.confirm_no"))],
            on_decide=_on_trust_confirm,
            escape_value="cancel",
            risk="high" if target_trust is TrustLevel.L4_AUTONOMOUS else "medium",
        ))

    async def _ledger_cmd(self, log) -> None:
        ledger_store = getattr(self, "_ledger_store", None)
        run_id = getattr(self, "_daemon_run_id", None) or getattr(self, "_run_id", None)

        if ledger_store is None or run_id is None:
            await log.append_line(t("tui.ledger.no_ledger"), kind="system")
            return

        try:
            entries = ledger_store.replay(run_id)
        except Exception as e:  # noqa: BLE001
            await log.append_line(t("tui.ledger.read_failed", err=e), kind="error")
            return

        if not entries:
            await log.append_line(t("tui.ledger.empty", run_id=run_id), kind="system")
            return

        visible = [e for e in entries if e.action != "undo_done"]
        if not visible:
            await log.append_line(t("tui.ledger.all_undone", run_id=run_id), kind="system")
            return

        has_file_undo = any(
            e.undo_state == "available"
            and e.undo_token
            and e.undo_token.startswith("file:")
            for e in visible
        )

        widget = LedgerTable(entries=visible, run_id=run_id)
        await log.mount_block(widget)
        journal_path = _argos_dir() / "ledger" / f"{run_id}.jsonl"
        await log.append_line(
            t("tui.ledger.footer", path=journal_path, run_id=run_id),
            kind="system",
        )

    async def _setup_cmd(self, log) -> None:
        import os
        from argos import config as C
        config_dir = _argos_dir()
        config_path = config_dir / "config.json"
        env_path = config_dir / ".env"
        status = "ok"
        next_command = "argos"
        try:
            if C._has_config_file():
                cfg = C.load_config()
                active = cfg.active
                tier = cfg.tiers[active]
                model = tier.model
                image_input = "enabled" if tier.multimodal is True else "disabled" if tier.multimodal is False else "auto"
                env_name = cfg.key_envs.get(active, "")
                if env_name and os.environ.get(env_name):
                    key_source = f"environment:{env_name}"
                elif env_name and cfg.secrets.get(env_name):
                    key_source = f".env:{env_name}"
                else:
                    key_source = f"missing:{env_name or '(none)'}"
                    status = "needs key"
                    next_command = "argos setup"
            else:
                active = C.DEFAULT_TIER.name
                model = C.DEFAULT_TIER.model
                image_input = "auto"
                fallback_keys = ("ARGOS_LLM_KEY", "VITE_LLM_KEY", "VITE_MINIMAX_KEY")
                env_name = next((k for k in fallback_keys if os.environ.get(k)), "ARGOS_LLM_KEY")
                if any(os.environ.get(k) for k in fallback_keys):
                    key_source = f"environment:{env_name}"
                elif C.active_key() is not None:
                    key_source = ".env.local"
                else:
                    key_source = f"missing:{env_name}"
                    status = "needs setup"
                    next_command = "argos setup"
        except Exception as e:  # noqa: BLE001
            active = "(not configured)"
            model = "(unknown)"
            image_input = "unknown"
            key_source = f"error:{e}"
            status = "error"
            next_command = "argos setup"
        await log.append_line(
            t(
                "tui.setup.card",
                active=active,
                model=model,
                image_input=image_input,
                key_source=key_source,
                config_path=config_path,
                env_path=env_path,
                next_command=next_command,
                status=status,
            ),
            kind="system",
        )

    async def _cmd_voice(self, log, arg: str) -> None:
        if arg.strip():
            await log.append_line(t("tui.voice.usage"), kind="error")
            return
        await log.append_line(t("tui.voice.unavailable"), kind="warn")

    async def _journal_cmd(self, log, arg: str) -> None:
        ledger_dir = _argos_dir() / "ledger"
        parts = arg.split()
        if len(parts) > 1:
            await log.append_line(t("tui.journal.usage"), kind="error")
            return
        run_id = parts[0] if parts else getattr(self, "_daemon_run_id", None) or getattr(self, "_run_id", None)
        if run_id:
            journal_path = ledger_dir / f"{run_id}.jsonl"
            await log.append_line(t("tui.journal.with_id", path=journal_path), kind="system")
        else:
            await log.append_line(t("tui.journal.no_id", dir=ledger_dir), kind="system")

    async def _retry(self, log) -> None:
        if self._run_active:
            await log.append_line(t("tui.retry.busy"), kind="system")
            return
        last_goal: str | None = None
        for entry in reversed(getattr(self, "_input_history", []) or []):
            if not entry.startswith("/"):
                last_goal = entry
                break
        if last_goal:
            try:
                prompt_widget = self.query_one("#prompt", PromptArea)
                prompt_widget._refill(last_goal)
                prompt_widget.reset_history_nav()
            except Exception:  # noqa: BLE001
                pass
            await self.start_run(last_goal)
            return
        loop = self._loop_factory() if self._loop_factory is not None else None
        store = getattr(loop, "store", None) if loop is not None else None
        if store is None or not hasattr(store, "get_messages"):
            await log.append_line(t("tui.retry.no_store"), kind="error")
            return
        try:
            msgs = store.get_messages(self._session_id)
        except Exception as e:  # noqa: BLE001
            await log.append_line(t("tui.retry.read_failed", err=e), kind="error")
            return
        last_user = next(
            (m for m in reversed(msgs) if m.get("role") == "user" and (m.get("text") or "").strip()),
            None,
        )
        if last_user is None:
            await log.append_line(t("tui.retry.no_messages"), kind="system")
            return
        await self.start_run(last_user["text"])

    async def _enter_plan_mode(self, log) -> None:
        from argos.core.plan_mode import EnterPlanMode
        try:
            loop = self._loop_factory()
        except Exception as e:  # noqa: BLE001
            await log.append_line(t("tui.plan.factory_failed", err=e), kind="error")
            return
        msg = EnterPlanMode(loop)
        self._plan_mode = True
        self._set_plan_mode_indicators()
        await log.append_line(msg, kind="system")

    async def _hooks_cmd(self, log, arg: str) -> None:
        from argos.hooks import get_config, reload_config, HooksConfigError
        arg = arg.strip().lower()
        if arg == "reload":
            try:
                cfg = reload_config()
                await log.append_line(t("tui.hooks.reloaded", n=len(cfg.entries)), kind="system")
            except HooksConfigError as e:
                await log.append_line(t("tui.hooks.reload_failed", err=e), kind="error")
            return
        if arg:
            await log.append_line(t("tui.hooks.usage"), kind="error")
            return
        cfg = get_config()
        if not cfg.entries:
            await log.append_line(t("tui.hooks.empty", path=_argos_dir() / "hooks.json"), kind="system")
            return
        lines = [t("tui.hooks.header", n=len(cfg.entries))]
        for ev_name, entries in cfg.entries.items():
            lines.append(f" · {ev_name}:")
            for e in entries:
                matcher_str = f"matcher={e.matcher!r}" if e.matcher else t("tui.hooks.all_match")
                lines.append(f"   - {matcher_str}")
                for h in e.hooks:
                    cmd_short = h.command[:60] + ("..." if len(h.command) > 60 else "")
                    lines.append(f"     · {cmd_short}  (timeout={h.timeout}ms)")
        await log.append_line("\n".join(lines), kind="system")

    async def _lsp_cmd(self, log, arg: str) -> None:
        from argos import lsp as _lsp
        from argos.lsp import get_config, reload_config, LspConfigError
        arg = arg.strip().lower()
        if arg == "reload":
            try:
                cfg = reload_config()
                await log.append_line(
                    t("tui.lsp.reloaded", n=len(cfg.servers)),
                    kind="system",
                )
            except LspConfigError as e:
                await log.append_line(t("tui.lsp.reload_failed", err=e), kind="error")
            return
        if arg:
            await log.append_line(t("tui.lsp.usage"), kind="error")
            return
        cfg = get_config()
        if not cfg.servers:
            await log.append_line(
                t("tui.lsp.empty", path=_argos_dir() / "lsp.json"),
                kind="system",
            )
            return
        try:
            mgr = _lsp.get_manager()
            servers = mgr.list_servers()
        except Exception as e:  # noqa: BLE001
            await log.append_line(t("tui.lsp.init_failed", err=e), kind="error")
            return
        lines = [t("tui.lsp.header", n=len(servers))]
        for s in servers:
            ft = ",".join(s["filetypes"])
            disabled_tag = " (disabled)" if cfg.servers.get(s["name"], None) and cfg.servers[s["name"]].disabled else ""
            lines.append(
                f" · {s['name']:<12} status={s['status']:<11} "
                f"ft={ft:<20} cmd={s['command']}{disabled_tag}"
            )
            if s.get("diag_count", 0) > 0:
                lines.append(t("tui.lsp.diag", n=s["diag_count"]))
        await log.append_line("\n".join(lines), kind="system")

    async def _permissions_cmd(self, log, arg: str) -> None:
        from argos.permissions import (
            get_config, reload_config, PermissionsConfigError,
        )
        arg = arg.strip().lower()
        if arg == "reload":
            try:
                cfg = reload_config()
                self.gate._permissions_config = cfg
                _dfl = cfg.default_level or t("tui.permissions.default_gate")
                await log.append_line(
                    t("tui.permissions.reloaded",
                      allow=len(cfg.allow), deny=len(cfg.deny),
                      ask=len(cfg.ask), tools=len(cfg.tools), level=_dfl),
                    kind="system",
                )
            except PermissionsConfigError as e:
                await log.append_line(
                    t("tui.permissions.reload_failed", err=e), kind="error",
                )
            return
        if arg:
            await log.append_line(t("tui.permissions.usage"), kind="error")
            return
        try:
            cfg = get_config()
        except Exception as e:  # noqa: BLE001
            await log.append_line(t("tui.permissions.read_failed", err=e), kind="error")
            return
        _dfl = cfg.default_level or t("tui.permissions.default_gate")
        lines = [
            t("tui.permissions.header"),
            t("tui.permissions.default_level", level=_dfl),
            t("tui.permissions.per_tool", n=len(cfg.tools)) + (
                "  " + ", ".join(f"{_t}={lv}" for _t, lv in cfg.tools.items()) if cfg.tools else ""
            ),
            t("tui.permissions.allow_rules", n=len(cfg.allow)),
        ]
        for e in list(cfg.allow)[:5]:
            lines.append(f"   · {e.tool}  matcher={e.matcher!r}")
        if len(cfg.allow) > 5:
            lines.append(t("tui.permissions.omitted", total=len(cfg.allow), omitted=len(cfg.allow) - 5))
        lines.append(t("tui.permissions.deny_rules", n=len(cfg.deny)))
        for e in list(cfg.deny)[:5]:
            lines.append(f"   · {e.tool}  matcher={e.matcher!r}")
        lines.append(t("tui.permissions.ask_rules", n=len(cfg.ask)))
        for e in list(cfg.ask)[:5]:
            lines.append(f"   · {e.tool}  matcher={e.matcher!r}")
        await log.append_line("\n".join(lines), kind="system")

    async def _show_tools(self, log) -> None:
        from argos import tools as _tools
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
        import os as _os_wf
        _wf_label = t("tui.tools.wf_off") if _os_wf.environ.get("ARGOS_WORKFLOWS", "1") == "0" else t("tui.tools.wf_on")
        groups = [
            (t("tui.tools.group.file"), ["read_file", "write_file", "edit_file", "search_files"]),
            (t("tui.tools.group.cmd"), ["run_command", "propose_verify", "update_plan"]),
            (t("tui.tools.group.web"), ["web_search", "web_extract"]),
            (t("tui.tools.group.browser"), [n for n in names if n.startswith("browser_")]),
            (t("tui.tools.group.external"), ["mcp_call"]),
            (t("tui.tools.group.lsp"), [n for n in names if n.startswith("lsp_")]),
            (t("tui.tools.group.os"), [n for n in names
                                if n.startswith("computer_")]),
            (_wf_label, ["propose_workflow"]),
        ]
        lines = [t("tui.tools.header", n=len(names))]
        for label, members in groups:
            present = [m for m in members if m in names]
            if present:
                lines.append(f" · {label}:{', '.join(present)}")
        await log.append_line("\n".join(lines), kind="system")

    async def _runs_cmd(self, log, arg: str) -> None:
        if not self._with_daemon or not self._daemon_client or not self._daemon_session_id:
            await log.append_line(
                t("tui.runs.no_daemon"),
                kind="error",
            )
            return
        rec = self._daemon_client.__class__  # type: ignore[attr-defined]
        parts = arg.split(None, 1)
        if not parts:
            try:
                runs = await self._daemon_client.list_runs(self._daemon_session_id)
            except Exception as e:  # noqa: BLE001
                await log.append_line(t("tui.runs.list_failed", err=e), kind="error")
                return
            if not runs:
                await log.append_line(t("tui.runs.empty"), kind="system")
                return
            import time as _time
            from argos.tui.widgets.tab_strip import _format_cost
            _ICON = {
                "pending": "◌", "running": "◉", "paused": "◔",
                "suspended": "◌", "completed": "◕",
                "failed": "◉", "cancelled": "◌",
            }
            lines = [t("tui.runs.list_header")]
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
            lines.append(t("tui.runs.list_footer", id="{id}"))
            await log.append_line("\n".join(lines), kind="system")
            return
        # /runs {id} [focus|resume|cancel]
        run_id = parts[0]
        action = parts[1].strip().lower() if len(parts) > 1 else "info"
        if action not in {"info", "focus", "resume", "cancel"}:
            await log.append_line(t("tui.runs.usage"), kind="error")
            return
        if action == "focus":
            try:
                status, _, _ = await self._daemon_client._request(
                    "POST", f"/runs/{run_id}/focus", session_id=self._daemon_session_id,
                )
                if status == 200:
                    self._daemon_run_id = run_id
                    await log.append_line(
                        t("tui.runs.focus_ok", run_id=run_id),
                        kind="system",
                    )
                    self._refresh_tab_strip()
                else:
                    await log.append_line(
                        t("tui.runs.focus_failed", status=status), kind="error",
                    )
            except Exception as e:  # noqa: BLE001
                err = str(e)
                if "session_readonly" in err or "403" in err:
                    await log.append_line(
                        t("tui.runs.focus_readonly"),
                        kind="error",
                    )
                else:
                    await log.append_line(t("tui.runs.focus_err", err=e), kind="error")
            return
        if action == "resume":
            try:
                await self._daemon_client.resume(self._daemon_session_id, run_id)
                await log.append_line(t("tui.runs.resume_ok", run_id=run_id), kind="system")
            except Exception as e:  # noqa: BLE001
                await log.append_line(t("tui.runs.resume_failed", err=e), kind="error")
        elif action == "cancel":
            try:
                await self._daemon_client.cancel(self._daemon_session_id, run_id)
                await log.append_line(t("tui.runs.cancel_ok", run_id=run_id), kind="system")
            except Exception as e:  # noqa: BLE001
                await log.append_line(t("tui.runs.cancel_failed", err=e), kind="error")
        else:
            try:
                info = await self._daemon_client.get_run(self._daemon_session_id, run_id)
                from argos.tui.widgets.tab_strip import _format_cost
                cost = _format_cost(info.get("cost_usd"))
                wt = info.get("worktree_path") or "(none)"
                journal_path = _argos_dir() / "ledger" / f"{run_id}.jsonl"
                await log.append_line(
                    f"{run_id}: state={info.get('state')}  events={info.get('events_count')}  "
                    f"cost={cost}  worktree={wt}\n"
                    f"  journal: {journal_path}",
                    kind="system",
                )
            except Exception as e:  # noqa: BLE001
                await log.append_line(t("tui.runs.info_failed", err=e), kind="error")


    async def _orders_cmd(self, log) -> None:
        if self._with_daemon and self._daemon_client and self._daemon_session_id:
            try:
                status, _, raw = await self._daemon_client._request(
                    "GET", "/orders", session_id=self._daemon_session_id,
                )
                import json as _json
                orders = _json.loads(raw)
            except Exception as e:  # noqa: BLE001
                await log.append_line(t("tui.orders.request_failed", err=e), kind="error")
                return
        else:
            try:
                from argos.conductor.orders import OrderStore
                orders = [o.to_dict() for o in OrderStore().list()]
            except Exception as e:  # noqa: BLE001
                await log.append_line(t("tui.orders.local_failed", err=e), kind="error")
                return

        from argos.tui.widgets.transcript import Transcript
        await self.query_one("#transcript", Transcript).mount_block(OrdersPanel(orders=orders))

    async def _confirm_suggestion_cmd(self, log, suggestion_id: str) -> None:
        parts = suggestion_id.split()
        if len(parts) != 1:
            await log.append_line(t("tui.confirm.no_id"), kind="error")
            return
        suggestion_id = parts[0]
        if not self._with_daemon or not self._daemon_client or not self._daemon_session_id:
            await log.append_line(
                t("tui.confirm.no_daemon"),
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
            await log.append_line(t("tui.confirm.request_failed", err=e), kind="error")
            return
        if status == 201:
            run_id = body.get("run_id", "?")
            wt = body.get("worktree_path") or "(none)"
            await log.append_line(
                t("tui.confirm.ok", run_id=run_id, wt=wt),
                kind="done",
            )
        elif status == 404:
            await log.append_line(
                t("tui.confirm.not_found", id=suggestion_id),
                kind="error",
            )
        elif status == 503:
            await log.append_line(
                t("tui.confirm.unavailable", err=body.get("error", t("tui.confirm.service_unavailable"))),
                kind="error",
            )
        else:
            await log.append_line(
                t("tui.confirm.failed", status=status, err=body.get("error", raw)),
                kind="error",
            )

    async def _dismiss_suggestion_cmd(self, log, suggestion_id: str) -> None:
        parts = suggestion_id.split()
        if len(parts) != 1:
            await log.append_line(t("tui.dismiss.no_id"), kind="error")
            return
        suggestion_id = parts[0]
        if not self._with_daemon or not self._daemon_client or not self._daemon_session_id:
            await log.append_line(
                t("tui.dismiss.no_daemon"),
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
            await log.append_line(t("tui.dismiss.request_failed", err=e), kind="error")
            return
        if status == 200:
            await log.append_line(t("tui.dismiss.ok", id=suggestion_id), kind="system")
        elif status == 404:
            await log.append_line(
                t("tui.dismiss.not_found", id=suggestion_id),
                kind="error",
            )
        else:
            await log.append_line(
                t("tui.dismiss.failed", status=status, err=body.get("error", raw)),
                kind="error",
            )


    async def _on_proactive_suggestion(self, ev) -> None:
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


    async def _on_computer_action(self, ev: "ComputerActionEvent") -> None:  # type: ignore[name-defined]
        from argos.tui.widgets.transcript import Transcript
        try:
            log = self.query_one("#transcript", Transcript)
        except Exception:  # noqa: BLE001
            return

        kind = ev.kind_action
        ok_mark = "✓" if ev.ok else "✗"

        if kind == "screenshot":
            if ev.ok:
                path_hint = f" → {ev.artifact_path}" if ev.artifact_path else ""
                line = t("tui.computer.screenshot_ok", mark=ok_mark, path=path_hint)
            else:
                line = t("tui.computer.screenshot_fail", mark=ok_mark, detail=ev.detail)
        elif kind in ("click", "double_click"):
            _label = t("tui.computer.dblclick_label") if kind == "double_click" else t("tui.computer.click_label")
            _coord = f"({ev.x}, {ev.y})" if ev.x is not None and ev.y is not None else t("tui.computer.unknown_coord")
            if ev.ok:
                line = t("tui.computer.click_ok", mark=ok_mark, label=_label, coord=_coord)
            else:
                line = t("tui.computer.click_fail", mark=ok_mark, label=_label, coord=_coord, detail=ev.detail)
        elif kind == "type_text":
            preview = ev.text_preview[:40] + ("…" if len(ev.text_preview) > 40 else "") if ev.text_preview else ""
            if ev.ok:
                line = t("tui.computer.type_ok", mark=ok_mark, preview=preview) if preview else t("tui.computer.type_ok_nopreview", mark=ok_mark)
            else:
                line = t("tui.computer.type_fail", mark=ok_mark, detail=ev.detail)
        elif kind == "key":
            preview = ev.text_preview or ""
            _detail = f":{ev.detail}" if not ev.ok else ""
            line = t("tui.computer.key_line", mark=ok_mark, preview=preview, detail=_detail)
        elif kind == "scroll":
            _coord = f"({ev.x}, {ev.y})" if ev.x is not None and ev.y is not None else ""
            _detail = f":{ev.detail}" if not ev.ok else ""
            line = t("tui.computer.scroll_line", mark=ok_mark, coord=_coord, detail=_detail)
        elif kind == "open_app":
            app_hint = ev.text_preview or ev.detail
            _detail = "" if ev.ok else f":{ev.detail}"
            line = t("tui.computer.open_app_line", mark=ok_mark, hint=app_hint, detail=_detail)
        else:
            line = t("tui.computer.generic_line", mark=ok_mark, kind=kind, detail=ev.detail)

        kind_str = "system" if ev.ok else "error"
        try:
            await log.append_line(line, kind=kind_str)
        except Exception:  # noqa: BLE001
            pass

    async def _skill_cmd(self, log, skill_name: str, arg: str) -> None:
        from pathlib import Path as _P
        from argos.skills_runtime.analysis import AnalysisSkillContext
        from argos.skills_runtime import run_skill, register_builtin_skills

        register_builtin_skills()
        path = arg.strip() or None
        workspace = getattr(self, "_workspace", None) or _P.cwd()
        ctx = AnalysisSkillContext(
            workspace=workspace, approval_level="auto", run_id=f"slash-{skill_name}",
        )
        try:
            result = await run_skill(skill_name, {"path": path}, ctx)
        except Exception as e:  # noqa: BLE001
            await log.append_line(t("tui.skill.run_failed", name=skill_name, err=e), kind="error")
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
        if not text.strip():
            await log.append_line(t("tui.remember.usage"), kind="error")
            return
        from argos.memory import auto as _mem
        pid = _mem.project_id_for()
        e = _mem.remember(text, project_id=pid)
        if e is None:
            await log.append_line(t("tui.remember.duplicate"), kind="info")
            return
        await log.append_line(
            t("tui.remember.ok", scope=e.scope, value=e.value, id=e.id, conf=e.confidence),
            kind="done",
        )

    async def _forget_cmd(self, log, query: str) -> None:
        if not query.strip():
            await log.append_line(t("tui.forget.usage"), kind="error")
            return
        from argos.memory import auto as _mem
        pid = _mem.project_id_for()
        sid = self._session_id
        out = _mem.forget(query, project_id=pid, session_id=sid)
        if not out:
            await log.append_line(t("tui.forget.not_found", query=query), kind="info")
            return
        await log.append_line(t("tui.forget.ok", n=len(out)), kind="done")
        for e in out:
            await log.append_line(f"  - {e.id} ({e.scope}) {e.key} = {e.value[:60]}",
                                 kind="info")

    async def _memory_cmd(self, log) -> None:
        from argos.memory import auto as _mem
        pid = _mem.project_id_for()
        sid = self._session_id
        text = _mem.view_all(project_id=pid, session_id=sid)
        await log.append_line(text, kind="system")

    async def _eval_cmd(self, log, arg: str) -> None:
        import time as _time
        from argos.eval.results import list_runs, summary
        if not arg.strip():
            runs = list_runs(limit=20)
            if not runs:
                await log.append_line(
                    t("tui.eval.no_runs"),
                    kind="system")
                return
            lines = [
                t("tui.eval.list_header"),
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
        parts = arg.split()
        sub = parts[0].lower()
        if sub == "run" and len(parts) == 2:
            await self._eval_run_cmd(log, parts[1])
            return
        if sub == "compare" and len(parts) == 3:
            await self._eval_compare_cmd(log, parts[1], parts[2])
            return
        await log.append_line(
            t("tui.eval.usage"), kind="error")

    async def _eval_run_cmd(self, log, task_id: str) -> None:
        from argos.eval.corpus import load_task
        from argos.eval.runner import PASS_PASSED
        from argos.eval.results import append as append_result
        from argos.cli.eval import _make_runner as _make_eval_runner
        try:
            task = load_task(task_id)
        except FileNotFoundError as e:
            await log.append_line(t("tui.eval.task_not_found", err=e), kind="error")
            return
        model_tier = "default"
        try:
            from argos import config as _cfg
            if _cfg._has_config_file():
                model_tier = _cfg.load_config().active
        except Exception:  # noqa: BLE001
            pass
        base = _argos_dir() / "eval"
        await log.append_line(
            f"[eval] task={task.id} category={task.category} difficulty={task.difficulty} "
            f"model={model_tier}")
        runner = _make_eval_runner(base=base)
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
        from argos.eval.corpus import load_task
        from argos.eval.compare import run_pair, write_report
        from argos.cli.eval import _make_runner as _make_eval_runner
        def _parse(spec: str) -> tuple[str | None, str | None]:
            if ":" in spec:
                tid, m = spec.split(":", 1)
                return tid, m
            return spec, None
        ta, ma = _parse(a)
        tb, mb = _parse(b)
        if not (ta and tb):
            await log.append_line(
                t("tui.eval.compare_usage"), kind="error")
            return
        if ta != tb:
            await log.append_line(t("tui.eval.task_mismatch", a=ta, b=tb), kind="error")
            return
        try:
            task = load_task(ta)
        except FileNotFoundError as e:
            await log.append_line(t("tui.eval.task_not_found", err=e), kind="error")
            return
        active = "default"
        try:
            from argos import config as _cfg
            if _cfg._has_config_file():
                active = _cfg.load_config().active
        except Exception:  # noqa: BLE001
            pass
        ma = ma or active
        mb = mb or active
        base = _argos_dir() / "eval"
        await log.append_line(f"[eval] A/B: {ma} vs {mb} on {ta} ...")
        runner = _make_eval_runner(base=base)
        ra, rb = run_pair(runner, task, model_a=ma, model_b=mb)
        p = write_report(ra, rb, base=base)
        md = p.read_text("utf-8")
        if md.count("\n") > 200:
            await log.append_line(
                md[:8000] + t("tui.eval.truncated", path=str(p)),
                kind="system")
        else:
            await log.append_line(md, kind="system")

    async def _routing_cmd(self, log, arg: str) -> None:
        parts = arg.strip().split()
        if parts and parts[0].lower() == "set":
            await self._routing_set(log, " ".join(parts[1:]))
            return
        if parts:
            from argos.routing.categorizer import TaskCategory
            await log.append_line(
                t("tui.routing.set_usage", cats=str([c.value for c in TaskCategory])),
                kind="error")
            return
        router = self._current_router()
        if router is None:
            await log.append_line(
                t("tui.routing.no_router"),
                kind="system")
            return
        widget = RoutingTable(routing=router.routing, history=router.history())
        from argos.tui.widgets.transcript import Transcript
        await self.query_one("#transcript", Transcript).mount_block(widget)

    async def _context_cmd(self, log, arg: str) -> None:
        from argos.context.analyzer import analyze
        from argos.context.render import format_json, format_table
        fmt = arg.strip().lower()
        if fmt not in ("", "--json"):
            await log.append_line(t("tui.context.usage"), kind="error")
            return
        loop = getattr(self, "_agent_loop", None)
        store = getattr(self, "_store", None)
        workspace = getattr(self, "_workspace", None) or (_argos_dir() / "workspace")
        try:
            b = analyze(loop, store=store, workspace=workspace)  # type: ignore[arg-type]
        except Exception as e:  # noqa: BLE001
            await log.append_line(t("tui.context.failed", err=e), kind="error")
            return
        if fmt == "--json":
            await log.append_line(format_json(b), kind="info")
            return
        for line in format_table(b).split("\n"):
            await log.append_line(line, kind="info")


    @staticmethod
    def _fmt_dream_report(r: dict) -> str:
        return t(
            "tui.dream.fmt",
            units=r.get("units_total", 0),
            promoted=r.get("promoted", 0),
            rejected=r.get("rejected", 0),
            skipped=r.get("skipped", 0),
            merged=r.get("memory_merged", 0),
            archived=r.get("memory_archived", 0),
        )

    async def _dream_cmd(self, log, arg: str) -> None:
        import json as _json

        sub = arg.strip().lower()
        if sub and sub != "status":
            await log.append_line(t("tui.dream.usage"), kind="error")
            return

        if not self._with_daemon or not self._daemon_client or not self._daemon_session_id:
            await log.append_line(
                t("tui.dream.no_daemon", path=_argos_dir() / "daemon.sock"),
                kind="error",
            )
            return

        if sub == "status":
            try:
                status, _, raw = await self._daemon_client._request(
                    "GET", "/dream/report", session_id=self._daemon_session_id,
                )
                body = _json.loads(raw) if raw else {}
            except Exception as e:  # noqa: BLE001
                await log.append_line(t("tui.dream.report_failed", err=e), kind="error")
                return
            if status == 200:
                report = body.get("report")
                if report is None:
                    await log.append_line(t("tui.dream.no_report"), kind="system")
                elif not isinstance(report, dict):
                    await log.append_line(
                        t("tui.dream.report_bad_type", type=type(report).__name__),
                        kind="error",
                    )
                else:
                    await log.append_line(self._fmt_dream_report(report), kind="done")
            else:
                await log.append_line(t("tui.dream.http_failed", status=status), kind="error")
            return

        try:
            status, _, raw = await self._daemon_client._request(
                "POST", "/dream/run", session_id=self._daemon_session_id,
            )
            body = _json.loads(raw) if raw else {}
        except Exception as e:  # noqa: BLE001
            await log.append_line(t("tui.dream.run_failed", err=e), kind="error")
            return

        if status == 202:
            await log.append_line(t("tui.dream.started"), kind="done")
            self._dream_card = DreamReportCard()
            await log.mount_block(self._dream_card)
        elif status == 409:
            await log.append_line(t("tui.dream.already_running"), kind="system")
        elif status == 503:
            msg = body.get("error") or body.get("state") or t("tui.dream.no_worker_key")
            await log.append_line(t("tui.dream.start_failed", msg=msg), kind="error")
        else:
            await log.append_line(
                t("tui.dream.unknown_status", status=status, body=body), kind="error"
            )

    def _parse_verify_arg(self, arg: str) -> tuple[str, str | None]:
        # pipe syntax: "text | verify: cmd"
        m = re.search(r"\|\s*verify:\s*(.+)$", arg, re.IGNORECASE)
        if m:
            goal_text = arg[:m.start()].strip()
            return goal_text, m.group(1).strip()
        # flag syntax: "text --verify cmd"
        m = re.search(r"--verify\s+(.+)$", arg, re.IGNORECASE)
        if m:
            goal_text = arg[:m.start()].strip()
            return goal_text, m.group(1).strip()
        return arg.strip(), None

    async def _goal_cmd(self, log, cmd_name: str, arg: str) -> None:
        if cmd_name == "loop":
            arg = re.sub(r"\buntil:\s*", "| verify: ", arg, count=1, flags=re.IGNORECASE)

        if re.search(r"\|\s*verify:\s*$", arg, re.IGNORECASE) or re.search(r"--verify\s*$", arg, re.IGNORECASE):
            await log.append_line(t("tui.goal.usage"), kind="error")
            return

        goal_text, verify_cmd = self._parse_verify_arg(arg)

        if not goal_text:
            await log.append_line(
                t("tui.goal.usage"),
                kind="error",
            )
            return

        if self._run_active:
            await log.append_line(t("tui.run.busy"))
            return

        if verify_cmd:
            await log.append_line(t("tui.goal.submitted", verify_cmd=verify_cmd), kind="system")

        await self.start_run(goal_text, verify_cmd=verify_cmd)

    async def _schedule_cmd(self, log, arg: str) -> None:
        # parse "every 1h: summarize logs" → schedule="every 1h", goal="summarize logs"
        if ":" not in arg:
            await log.append_line(t("tui.schedule.usage"), kind="error")
            return
        when, _, goal = arg.partition(":")
        when = when.strip()
        goal = goal.strip()
        if not when or not goal:
            await log.append_line(t("tui.schedule.usage"), kind="error")
            return
        if not self._with_daemon or not self._daemon_client:
            await log.append_line(t("tui.schedule.needs_daemon"), kind="error")
            return
        body = {
            "utterance": f"/schedule {arg}",
            "kind": "schedule",
            "schedule": when,
            "goal_template": goal,
        }
        try:
            status, data = await self._daemon_client.create_order(self._daemon_session_id, body)
        except Exception as e:  # noqa: BLE001
            await log.append_line(t("tui.orders.request_failed", err=e), kind="error")
            return
        if status == 201:
            await log.append_line(t("tui.schedule.created", id=data.get("id", "?")), kind="done")
        else:
            await log.append_line(t("tui.orders.http_failed", status=status), kind="error")

    async def _watch_cmd(self, log, arg: str) -> None:
        parts = arg.strip().split(None, 1)
        if len(parts) < 2:
            await log.append_line(t("tui.watch.usage"), kind="error")
            return
        glob_pat, goal = parts[0], parts[1].strip()
        if not goal:
            await log.append_line(t("tui.watch.usage"), kind="error")
            return
        if not self._with_daemon or not self._daemon_client:
            await log.append_line(t("tui.watch.needs_daemon"), kind="error")
            return
        body = {
            "utterance": f"/watch {arg}",
            "kind": "file_trigger",
            "trigger_glob": glob_pat,
            "goal_template": goal,
        }
        try:
            status, data = await self._daemon_client.create_order(self._daemon_session_id, body)
        except Exception as e:  # noqa: BLE001
            await log.append_line(t("tui.orders.request_failed", err=e), kind="error")
            return
        if status == 201:
            await log.append_line(t("tui.watch.created", id=data.get("id", "?")), kind="done")
        else:
            await log.append_line(t("tui.orders.http_failed", status=status), kind="error")

    async def _routing_set(self, log, arg: str) -> None:
        import os
        from pathlib import Path
        from argos import config as _cfg
        from argos.config import ConfigError
        from argos.routing.categorizer import TaskCategory
        from argos.routing.config import set_category

        parts = arg.strip().split()
        if len(parts) != 2:
            await log.append_line(
                t("tui.routing.set_usage", cats=str([c.value for c in TaskCategory])),
                kind="error")
            return
        cat_name, tier = parts
        try:
            category = TaskCategory(cat_name)
        except ValueError:
            await log.append_line(
                t("tui.routing.bad_category", cat=cat_name, cats=str([c.value for c in TaskCategory])),
                kind="error")
            return
        try:
            config_dir = Path(_cfg.get("ARGOS_CONFIG_DIR") or (Path.home() / ".argos")).expanduser()
            _cfg.tier_for(tier)
            if _cfg.key_for(tier) is None:
                cfg = _cfg.load_config()
                env_name = cfg.key_envs.get(tier) or ""
                raise ConfigError(
                    t("tui.routing.missing_key", name=tier, env=env_name)
                )
            set_category(config_dir, category, tier)
        except ConfigError as e:
            await log.append_line(t("tui.routing.set_failed", err=e), kind="error")
            return
        await log.append_line(
            t("tui.routing.set_ok", dir=config_dir, cat=category.value, tier=tier),
            kind="done")

    def _current_router(self):
        loop = getattr(self, "_current_loop", None)
        if loop is None:
            return None
        return getattr(loop, "_router", None)

    async def _show_skills(self, log) -> None:
        cmd_arg = getattr(self, "_last_skills_arg", "")
        sub_parts = cmd_arg.split()
        known_subcommands = ("install", "remove", "refresh", "test")
        sub = sub_parts[0].lower() if sub_parts else ""
        if sub_parts and sub not in known_subcommands:
            await log.append_line(t("tui.skills.usage"), kind="error")
            return
        if sub_parts and sub in known_subcommands:
            sub_arg = sub_parts[1] if len(sub_parts) > 1 else ""
            if sub in ("install", "remove", "test") and len(sub_parts) != 2:
                await log.append_line(
                    t("tui.skills.named_usage", sub=sub) if not sub_arg else t("tui.skills.usage"),
                    kind="error",
                )
                return
            if sub == "refresh" and len(sub_parts) != 1:
                await log.append_line(t("tui.skills.usage"), kind="error")
                return
            await log.append_line(t("tui.skills.side_effect_hint", sub=sub, arg=sub_arg), kind="system")
            return

        try:
            from argos.skills_curator.capabilities import list_installed
            from argos.skills_curator.index import cache_age_days, load_cache
            from argos.skills_curator.recommend import (
                SessionActivity, build_activity_from_session, recommend,
            )
        except Exception as e:  # noqa: BLE001
            await log.append_line(t("tui.skills.curator_failed", err=e), kind="error")
            return

        installed = list_installed()
        by_name = {s.name: s for s in installed}
        cache = load_cache()
        lines: list[str] = []
        lines.append(f"Installed skills ({len(installed)}):")
        if not installed:
            lines.append(t("tui.skills.empty"))
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
        try:
            from argos import mcp_native
            mgr = mcp_native.get_manager()
            tools = mgr.list_tools()
        except Exception as e:  # noqa: BLE001
            await log.append_line(t("tui.mcp.query_failed", err=e), kind="error")
            return
        if not tools:
            await log.append_line(
                t("tui.mcp.empty", path=_argos_dir() / "mcp.json"),
                kind="system")
            return
        by_server: dict[str, list] = {}
        for _tool in tools:
            by_server.setdefault(_tool.server, []).append(_tool)
        lines = [t("tui.mcp.header", n=len(tools))]
        for server, ts in by_server.items():
            lines.append(f" · {server}:{', '.join(_tool.name for _tool in ts)}")
        await log.append_line("\n".join(lines), kind="system")

    async def _resume_recent(self, log) -> None:
        loop = self._loop_factory()
        store = getattr(loop, "store", None)
        if store is None or not hasattr(store, "list_sessions"):
            await log.append_line(t("tui.resume.no_store"), kind="error")
            return
        sessions = [s for s in store.list_sessions(limit=10) if s.session_id != self._session_id]
        if not sessions:
            await log.append_line(t("tui.resume.no_sessions"), kind="system")
            return
        prev = sessions[0]
        self._session_id = prev.session_id
        msgs = store.get_messages(prev.session_id) if hasattr(store, "get_messages") else []
        title = (prev.title or prev.session_id[:8]).strip() or prev.session_id[:8]
        await log.append_line(
            t("tui.resume.ok", title=title, n=len(msgs)), kind="done")

    async def start_run(self, goal: str, attachments: list | None = None, *, verify_cmd: str | None = None) -> None:
        if self._run_active:
            return
        self._run_active = True
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
        self._step_blocks = {}
        self._current_plan_call_id = None
        _ap = self.query_one("#activity", ActivityPanel)
        _ap.reset_run()
        _ap.on_run_active(goal)
        try:
            from argos import hooks as _hooks
            from argos.hooks.payload import build_user_prompt_payload
            ups_payload = build_user_prompt_payload(
                session_id=self._session_id, cwd=str(self._workspace), goal=goal,
            )
            ups_result = await _hooks.fire(
                "UserPromptSubmit", ups_payload,
                cwd=self._workspace, session_id=self._session_id,
            )
            for h in ups_result.per_hook:
                await self._apply_event(HookFired(
                    event_name="UserPromptSubmit", command=h.command,
                    success=h.success, returncode=h.returncode,
                    elapsed_ms=h.elapsed_ms, timed_out=h.timed_out,
                    not_found=h.not_found, stop_reason=h.stop_reason,
                    error=h.error,
                ))
        except Exception:  # noqa: BLE001
            pass
        log = self.query_one("#transcript", Transcript)
        await log.user_line(goal)

        if self._with_daemon and self._daemon_client is not None and self._daemon_session_id:
            await self._start_run_daemon(goal, log, attachments or [], verify_cmd=verify_cmd)
        else:
            await self._start_run_inline(goal, log, attachments or [], verify_cmd=verify_cmd)

    async def _start_run_inline(self, goal: str, log, attachments: list | None = None, *, verify_cmd: str | None = None) -> None:
        bus = EventBus()
        # /goal | verify: <cmd> — pass verify_cmd into the factory so it lands in LoopConfig
        # (same dataclasses.replace pattern as build_run_stack; hasattr-assignment was a silent no-op
        # because AgentLoop stores it as _verify_cmd, not verify_cmd).
        loop = self._loop_factory(verify_cmd=verify_cmd)
        self._current_loop = loop

        await self._announce_memory_recall(log, loop, goal)
        await log.show_thinking(t("tui.run.thinking"))

        async def _produce() -> None:
            try:
                _run_kwargs = {"attachments": attachments} if attachments else {}
                async for ev in loop.run(goal, session_id=self._session_id, **_run_kwargs):
                    await bus.emit(ev)
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
            self._glow_stop()
            try:
                self.query_one("#activity", ActivityPanel).on_run_end()
                self.query_one("#status-bar", StatusBar).mark_run_end()
            except Exception:  # noqa: BLE001
                pass
            if self._interrupted:
                await log.append_line(t("tui.run.interrupted"), kind="system")
                self._interrupted = False

    async def _start_run_daemon(
        self, goal: str, log, attachments: list | None = None, *, verify_cmd: str | None = None
    ) -> None:
        from argos.tui.daemon_source import DaemonEventSource
        assert self._daemon_client is not None
        assert self._daemon_session_id is not None

        try:
            run_id = await self._daemon_create_run(goal, attachments, verify_cmd=verify_cmd)
        except Exception as e:  # noqa: BLE001
            await log.append_line(t("tui.run.create_failed", err=e), kind="error")
            self._run_active = False
            self._glow_stop()
            return

        self._daemon_run_id = run_id

        self._refresh_tab_strip()

        await log.show_thinking(t("tui.run.thinking"))

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
                self.query_one("#status-bar", StatusBar).mark_run_end()
            except Exception:  # noqa: BLE001
                pass
            if self._interrupted:
                await log.append_line(t("tui.run.interrupted"), kind="system")
                self._interrupted = False

    async def _announce_memory_recall(self, log, loop: object, goal: str) -> None:
        pass

    def _apply_phase_event(self, ev: PhaseChange, log, bar, ap) -> None:
        from argos.tui import glow
        for sp in log.query(ThinkingIndicator):
            sp.set_label({
                "plan": t("tui.event.phase.plan"),
                "act": t("tui.event.phase.act"),
                "verify": t("tui.event.phase.verify"),
                "report": t("tui.event.phase.report"),
            }.get(ev.phase, t("tui.event.phase.default")))
        log.finalize_response()
        bar.set_phase(ev.phase, ev.actions, ev.max_steps)
        ap.on_phase(ev.phase, ev.actions)
        if ev.phase == "plan" and self._terminal_glow:
            self._set_terminal_glow(False)
        if not self._terminal_glow:
            self._glow_base = glow.phase_color(ev.phase)
            self._set_border(self._glow_base)

    async def _apply_verdict_event(self, ev: VerifyVerdict, log, ap) -> None:
        from argos.tui import glow
        existing = list(self.query(VerdictBadge))
        if existing:
            badge = existing[0]
        else:
            badge = VerdictBadge(id="verdict-badge")
            await log.mount_block(badge)
        badge.show(ev.verdict)
        ap.on_verdict(ev.verdict)
        _is_no_test = bool(getattr(ev.verdict, "no_test", False))
        if _is_no_test:
            self._set_border(glow.IDLE_BORDER)
            self._set_terminal_glow(False)
        else:
            self._set_border(glow.verdict_color_self_aware(
                ev.verdict.status,
                self_verified=bool(getattr(ev.verdict, "self_verified", False)),
            ))
            if ev.verdict.status in ("failed", "unverifiable"):
                self._set_terminal_glow(
                    True, kind="warn" if ev.verdict.status == "unverifiable" else "fail")

    def _apply_cost_event(self, ev: CostUpdate, bar, ap) -> None:
        bar.set_cost(
            tokens_in=ev.tokens_in, tokens_out=ev.tokens_out,
            cost_usd=ev.cost_usd, elapsed_s=ev.elapsed_s,
        )
        ap.on_cost(
            tokens_in=ev.tokens_in, tokens_out=ev.tokens_out,
            cost_usd=ev.cost_usd, elapsed_s=ev.elapsed_s, cache_read=ev.cache_read,
            tier_name=ev.tier_name,
        )
        window = self._display_tier().context_window
        ap.on_context(used=ev.context_used, window=window)
        bar.update_ctx_pressure((ev.context_used / window) if window else 0.0)

    def _apply_dream_event(self, ev: DreamProgressEvent | DreamReportEvent, ap) -> None:
        dream_card = getattr(self, "_dream_card", None)
        if isinstance(ev, DreamProgressEvent):
            if dream_card is not None:
                try:
                    dream_card.append_stage(ev.stage, ev.detail or "")
                except Exception:  # noqa: BLE001
                    pass
            else:
                try:
                    detail = f" {ev.detail}" if ev.detail else ""
                    ap.append_line(f"[dream] {ev.stage}{detail}")
                except Exception:  # noqa: BLE001
                    pass
            return
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
            except Exception:  # noqa: BLE001
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
            except Exception:  # noqa: BLE001
                pass

    async def _apply_event(self, ev: Event) -> None:
        from argos.tui import glow
        log = self.query_one("#transcript", Transcript)
        bar = self.query_one("#status-bar", StatusBar)
        ap = self.query_one("#activity", ActivityPanel)
        if isinstance(ev, TokenDelta):
            await log.append_token(ev.text)
        elif isinstance(ev, PhaseChange):
            self._apply_phase_event(ev, log, bar, ap)
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
            await self._apply_verdict_event(ev, log, ap)
        elif isinstance(ev, CostUpdate):
            self._apply_cost_event(ev, bar, ap)
        elif isinstance(ev, PlanUpdate):
            ap.on_plan(ev.todos)
        elif isinstance(ev, CompactedEvent):
            try:
                ap.on_compacted(ev.before, ev.after, ev.reduction_pct)
            except Exception:  # noqa: BLE001
                pass
            pct = round(ev.reduction_pct * 100) if ev.reduction_pct <= 1 else round(ev.reduction_pct)
            await log.append_line(
                t("tui.event.compacted", pct=pct, before=ev.before, after=ev.after), kind="system")
        elif isinstance(ev, PrunedEvent):
            try:
                ap.on_pruned(ev.before, ev.after, ev.removed)
            except Exception:  # noqa: BLE001
                pass
            await log.append_line(t("tui.event.pruned", n=ev.removed), kind="system")
        elif isinstance(ev, HookFired):
            ap.on_hook_fired(ev)
        elif isinstance(ev, WorkflowProposed):
            await self._handle_workflow_proposed(ev)
        elif isinstance(ev, WorkflowProgress):
            if self._workflow_panel is not None:
                self._workflow_panel.update_progress(ev.agent_id, ev.phase, ev.note)
        elif isinstance(ev, WorkflowDone):
            if self._workflow_panel is not None:
                self._workflow_panel.finish(ev.synthesis, ev.notes)
            await log.append_line(
                t("tui.event.workflow_done", name=ev.name, synthesis=ev.synthesis), kind="done")
        elif isinstance(ev, ToolReceipt):
            ap.on_receipt(ev.receipt.action, ev.receipt.sig[:8])
        elif isinstance(ev, ApprovalRequest):
            await self._handle_approval(ev)
        elif isinstance(ev, PlanRendered):
            await self._handle_plan_rendered(ev)
        elif isinstance(ev, PlanDecisionRequest):
            self._current_plan_call_id = ev.call_id
        elif isinstance(ev, MemoryRecallEvent):
            n = len(ev.hits)
            if n > 0:
                await log.append_line(t("tui.event.memory_recall", n=n), kind="system")
                try:
                    ap.on_memory_recall(n)
                except Exception:  # noqa: BLE001
                    pass
        elif isinstance(ev, ApprovalResponse):
            await log.append_line(t("tui.event.approval_result", action=ev.call_id, value=ev.decision))
        elif isinstance(ev, ProactiveSuggestionEvent):
            await self._on_proactive_suggestion(ev)
        elif isinstance(ev, ComputerActionEvent):
            await self._on_computer_action(ev)
        elif isinstance(ev, DreamProgressEvent):
            self._apply_dream_event(ev, ap)
        elif isinstance(ev, DreamReportEvent):
            self._apply_dream_event(ev, ap)
        elif isinstance(ev, Escalation):
            await log.append_line(t("tui.event.escalation", attempts=ev.attempts, reason=ev.reason, failure=ev.last_failure), kind="escalation")
            self._set_border(glow.ERROR)
            self._set_terminal_glow(True, kind="warn")
        elif isinstance(ev, Error):
            chain = (" ← " + " ← ".join(ev.chain)) if ev.chain else ""
            await log.append_line(t("tui.event.error", message=ev.message, chain=chain), kind="error")
            self._set_border(glow.ERROR)
            self._set_terminal_glow(True)

    def action_ctrl_c(self) -> None:
        import time
        now = time.time()
        if self._run_active:
            self.action_interrupt()
            self._last_ctrl_c_time = 0.0
            return
        if (now - self._last_ctrl_c_time) < 1.5:
            self._last_ctrl_c_time = 0.0
            self.exit()
            return
        self._last_ctrl_c_time = now
        try:
            self.run_worker(
                self.query_one("#transcript", Transcript).append_line(
                    t("tui.ctrlc.hint"),
                    kind="system",
                ),
                exclusive=False,
            )
        except Exception:  # noqa: BLE001
            pass

    def action_interrupt(self) -> None:
        import time
        menu = self.query_one("#slash-menu", SlashMenu)
        if menu.display:
            menu.hide()
            return
        if not self._run_active or self._produce_worker is None:
            return
        now = time.time()
        if self._with_daemon and self._daemon_client is not None and self._daemon_session_id:
            if (now - self._last_esc_time) < 1.5:
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
            self._last_esc_time = now
            try:
                self.run_worker(self._daemon_pause(), exclusive=False)
            except Exception:  # noqa: BLE001
                pass
            return
        self._interrupted = True
        self._last_esc_time = 0.0
        try:
            self._produce_worker.cancel()
        except Exception:  # noqa: BLE001
            pass

    async def _daemon_pause(self) -> None:
        if not self._daemon_client or not self._daemon_session_id or not self._daemon_run_id:
            return
        try:
            await self._daemon_client.pause(self._daemon_session_id, self._daemon_run_id)
        except Exception as e:  # noqa: BLE001
            log = __import__("logging").getLogger(__name__)
            log.warning("daemon pause failed: %s", e)

    def action_background(self) -> None:
        if not self._with_daemon or not self._daemon_client or not self._daemon_session_id:
            return
        if not self._run_active or not self._daemon_run_id:
            return
        rid = self._daemon_run_id
        sid = self._daemon_session_id
        client = self._daemon_client

        async def _do() -> None:
            log_widget = self.query_one("#transcript", Transcript)
            try:
                resp = await client.suspend(sid, rid)
            except Exception as e:  # noqa: BLE001
                await log_widget.append_line(
                    t("tui.background.failed", err=e), kind="error")
                return
            if isinstance(resp, dict) and resp.get("state") == "suspend_requested":
                await log_widget.append_line(
                    t("tui.background.suspended", run_id=rid), kind="system")
            else:
                await log_widget.append_line(
                    t("tui.background.failed", err=resp), kind="error")

        self.run_worker(_do(), exclusive=False)

    def _set_blocked_status(self, active: bool) -> None:
        try:
            self.query_one("#status-bar", StatusBar).set_blocked(active)
        except Exception:  # noqa: BLE001
            pass

    async def _enqueue_choice(self, factory: Callable[[], InlineChoice]) -> None:
        self._choice_queue.append(factory)
        if not self._choice_active:
            await self._mount_next_choice()

    async def _mount_next_choice(self) -> None:
        if not self._choice_queue:
            self._choice_active = False
            self._set_blocked_status(False)
            return
        self._choice_active = True
        self._set_blocked_status(True)
        widget = self._choice_queue.popleft()()
        await self.query_one("#transcript", Transcript).mount_block(widget)

    def _choice_done(self) -> None:
        self._choice_active = False
        if self._choice_queue:
            self.run_worker(self._mount_next_choice(), exclusive=False)
        else:
            self._set_blocked_status(False)

    async def _handle_workflow_proposed(self, ev: WorkflowProposed) -> None:
        log = self.query_one("#transcript", Transcript)
        panel = WorkflowPanel(name=ev.name)
        self._workflow_panel = panel
        await log.mount_block(panel)
        if self.gate.level is ApprovalLevel.AUTO:
            return

        call_id = ev.call_id

        def _decide(value: str, _feedback: str) -> None:
            self.gate.respond(call_id, value)  # type: ignore[arg-type]
            self.run_worker(
                log.append_line(t("tui.event.workflow_approval", name=ev.name, value=value)),
                exclusive=False,
            )
            self._choice_done()

        await self._enqueue_choice(lambda: InlineChoice(
            title=t("tui.workflow.approval_title"),
            body=ev.preview,
            options=[
                ("once", t("tui.workflow.once")),
                ("always", t("tui.workflow.always")),
                ("deny", t("tui.workflow.deny")),
            ],
            on_decide=_decide,
            escape_value="deny",
            risk="medium",
        ))

    def _on_gate_ask(self, call_id: str, payload: dict) -> None:
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
        except Exception:  # noqa: BLE001
            pass

    async def _handle_approval(self, req: ApprovalRequest) -> None:
        if self.gate.level is ApprovalLevel.AUTO and not req.action.startswith("computer_"):
            if self._with_daemon and self._daemon_client and self._daemon_session_id and self._daemon_run_id:
                self.run_worker(
                    self._daemon_approval_post(req.call_id, "always"),
                    exclusive=False,
                )
            else:
                self.gate.respond(req.call_id, "always")
            return

        body_lines = [req.description, t("tui.approval.action_line", action=req.action, args=req.args)]
        if getattr(req, "secret_pattern", None):
            body_lines.append(t("tui.approval.secret_warning"))

        _is_daemon = (
            self._with_daemon
            and self._daemon_client is not None
            and self._daemon_session_id is not None
            and self._daemon_run_id is not None
        )

        def _decide(value: str, _feedback: str) -> None:
            if _is_daemon:
                self.run_worker(
                    self._daemon_approval_post(req.call_id, value),
                    exclusive=False,
                )
            else:
                self.gate.respond(req.call_id, value)  # type: ignore[arg-type]
            self.run_worker(
                self.query_one("#transcript", Transcript).append_line(
                    t("tui.event.approval_result", action=req.action, value=value)
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

        options = [
            ("once", t("tui.approval.once")),
            ("session", t("tui.approval.session")),
        ]
        if derive_persistent_allow_rule(req.action, req.args) is not None:
            options.append(("always", t("tui.approval.always")))
        options.append(("deny", t("tui.approval.deny")))

        await self._enqueue_choice(lambda: InlineChoice(
            title=format_approval_title(
                risk=req.risk, trigger=getattr(req, "trigger", "") or "",
            ),
            body="\n".join(body_lines),
            options=options,
            on_decide=_decide,
            escape_value="deny",
            risk=req.risk,
        ))

    async def _daemon_approval_post(self, call_id: str, decision: str) -> None:
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
        loop = self._current_loop

        if self.gate.level is ApprovalLevel.AUTO:
            call_id = getattr(self, "_current_plan_call_id", None)
            if self._with_daemon and self._daemon_client and self._daemon_session_id and self._daemon_run_id and call_id:
                self.run_worker(
                    self._daemon_plan_decision_post(call_id, "approve_start"),
                    exclusive=False,
                )
            elif loop is not None and hasattr(loop, "respond_plan_decision") and call_id:
                loop.respond_plan_decision(call_id, "approve_start", None)
            elif loop is not None:
                from argos.core.plan_mode import ExitPlanMode
                ExitPlanMode(loop, "approve_start")
            return

        if loop is None and not (self._with_daemon and self._daemon_run_id):
            return

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
                from argos.core.plan_mode import ExitPlanMode
                ExitPlanMode(loop, value, feedback if value == "refine" else None)
            self.run_worker(
                self.query_one("#transcript", Transcript).append_line(
                    t("tui.event.plan_decision", value=value), kind="system"
                ),
                exclusive=False,
            )
            self._choice_done()

        await self._enqueue_choice(lambda: InlineChoice(
            title=t("tui.plan.modal_title"),
            body=ev.plan_md,
            options=[
                ("approve_start", t("tui.plan.approve_start")),
                ("approve_accept_edits", t("tui.plan.approve_accept")),
                ("keep_planning", t("tui.plan.keep_planning")),
                ("refine", t("tui.plan.refine")),
            ],
            on_decide=_decide,
            escape_value=None,
            needs_input={"refine"},
            input_placeholder=t("tui.plan.refine_placeholder"),
            risk="plan",
        ))

    async def _daemon_plan_decision_post(self, call_id: str, action: str, feedback: str | None = None) -> None:
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
