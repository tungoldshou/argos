from __future__ import annotations

import time
from collections import deque

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Vertical
from textual.widgets import Static

_COL_PASS       = "#9ECE6A"
_COL_PASS_WEAK  = "#73A857"
_COL_FAIL       = "#F7768E"
_COL_UNVERIF    = "#FF9E64"
_COL_CYAN       = "#7DCFFF"
_COL_EYE        = "#D9A85C"
_COL_INK_BRIGHT = "#ECEEF5"
_COL_INK        = "#C8CCDA"
_COL_INK_DIM    = "#7E869C"
_COL_INK_FAINT  = "#6B7494"
_COL_INK_GHOST  = "#3A4055"

from argos.i18n import t as t_
from argos.tui.widgets._fmt import fmt_token_flow, fmt_tokens
from argos.hooks.events import HookFired
from argos.lsp.events import LspServerEvent, LspDiagnosticEvent
from argos.skills_runtime.events import SkillRunStart, SkillRunEnd

_PHASE_GLYPH = {"plan": "◔", "act": "◉", "verify": "❂", "report": "◕"}

_VIEWS = ("idle", "plan", "act", "verify")


class _Section(Static):
    DEFAULT_CSS = """
    _Section {
        height: auto;
        padding: 0 1;
        margin: 0 0 1 0;
        border-top: solid $hairline-lit;
        border-title-color: $eye-soft;
        border-title-style: bold;
        border-title-align: left;
    }
    """
    def __init__(self, title: str, body: str = "") -> None:
        super().__init__(body, markup=False)
        self.border_title = title


class ActivityPanel(Vertical):
    DEFAULT_CSS = """
    ActivityPanel { width: 34; background: $well; padding: 1 0 0 0; overflow-y: auto; scrollbar-size-vertical: 1; }
    ActivityPanel #view-header { color: $eye-soft; text-style: bold; padding: 0 1; margin: 0 0 1 0; }
    """

    _MODEL_IDX = 0
    _PROGRESS_IDX = 1
    _TOOLS_IDX = 2
    _RECEIPT_IDX = 3
    _RUN_IDX = 4
    _CATALOG_IDX = 5
    _MCP_IDX = 6
    _HOOK_IDX = 7
    _LSP_IDX = 8
    _SKILL_IDX = 9
    _APPROVAL_IDX = 10
    _VERDICT_IDX = 11
    _COST_IDX = 12
    _CTX_IDX = 13

    _VIEW_SECTIONS: dict[str, frozenset[int]] = {
        "idle": frozenset({_MODEL_IDX, _RUN_IDX, _CATALOG_IDX, _MCP_IDX, _VERDICT_IDX}),
        "plan": frozenset({_PROGRESS_IDX}),
        "act": frozenset({_PROGRESS_IDX, _TOOLS_IDX, _RECEIPT_IDX, _HOOK_IDX,
                          _LSP_IDX, _SKILL_IDX, _APPROVAL_IDX}),
        "verify": frozenset({_PROGRESS_IDX, _APPROVAL_IDX, _VERDICT_IDX}),
    }
    _FOOTER: frozenset[int] = frozenset({_COST_IDX, _CTX_IDX})

    def __init__(self, *, model_label: str = "—", tier: str = "—", **kwargs) -> None:
        super().__init__(**kwargs)
        self._model_label = model_label
        self._tier = tier
        self._phases: list[tuple[str, float, str]] = []   # (phase, elapsed, status)
        self._phase_start = 0.0
        self._tool_counts: dict[str, int] = {}
        self._receipts: list[tuple[str, str]] = []  # (action, sig_display[:8])
        self._todos: list[dict] = []
        self._hook_log: deque[HookFired] = deque(maxlen=50)
        self._lsp_servers: dict[str, str] = {}
        self._lsp_diag_cache: dict[str, int] = {}
        self._skill_runs: deque[SkillRunStart | SkillRunEnd] = deque(maxlen=20)
        self._approval_count: dict[str, int] = {"ok": 0, "ask": 0, "deny": 0}
        self._approval_log: deque[tuple[str, str, str]] = deque(maxlen=10)
        self._cache_history: deque[int] = deque(maxlen=8)
        self._cache_seen: bool = False
        self._compaction_line: str = ""
        self._view: str = "idle"
        self._pinned: bool = False
        self._verdict_shown: bool = False

    def compose(self) -> ComposeResult:
        yield Static(self._header_text(), id="view-header", markup=False)
        yield _Section(t_("widget.section_model"), self._model_label)
        yield _Section(t_("widget.section_progress"), t_("widget.progress_pending"))
        yield _Section(t_("widget.section_tools"), t_("widget.tools_zero"))
        yield _Section(t_("widget.section_receipt"), t_("widget.empty"))
        yield _Section(t_("widget.section_run"), t_("widget.empty"))
        yield _Section(t_("widget.section_skill_catalog"), self._skill_catalog_summary())
        yield _Section(t_("widget.section_mcp"), self._mcp_summary())
        yield _Section(t_("widget.section_hook"), t_("widget.empty"))
        yield _Section(t_("widget.section_lsp"), t_("widget.empty"))
        yield _Section(t_("widget.section_skill"), self._skill_summary())
        yield _Section(t_("widget.section_approval"), t_("widget.empty"))
        yield _Section(t_("widget.section_verdict"), t_("widget.empty"))
        yield _Section(t_("widget.section_cost"), f"{fmt_token_flow(0, 0)}\n" + t_("widget.cache_hit_line", cache_read=0, elapsed_s=0.0))
        yield _Section(t_("widget.section_context"), t_("widget.empty"))

    def on_mount(self) -> None:
        self._apply_view()

    def _header_text(self) -> str:
        pin = " *" if self._pinned else ""
        return t_("widget.view_header", view=self._view, pin=pin)

    def _apply_view(self) -> None:
        visible = self._VIEW_SECTIONS.get(self._view, frozenset()) | self._FOOTER
        for i, sec in enumerate(self._sections()):
            sec.display = i in visible
        try:
            self.query_one("#view-header", Static).update(self._header_text())
        except Exception:  # noqa: BLE001
            pass

    def set_view(self, view: str, *, pinned: bool | None = None) -> None:
        if view not in _VIEWS:
            return
        self._view = view
        if pinned is not None:
            self._pinned = pinned
        self._apply_view()

    def cycle_view(self) -> str:
        if not self._pinned:
            self._pinned = True
            self.set_view(_VIEWS[0])
            return _VIEWS[0]
        idx = _VIEWS.index(self._view) if self._view in _VIEWS else 0
        if idx + 1 < len(_VIEWS):
            self.set_view(_VIEWS[idx + 1])
            return _VIEWS[idx + 1]
        self._pinned = False
        self._apply_view()
        return "auto"

    def _auto_view(self, phase: str) -> None:
        if self._pinned:
            return
        view = {"plan": "plan", "act": "act", "verify": "verify", "report": "verify"}.get(phase)
        if view:
            self.set_view(view)

    def on_run_active(self, label: str) -> None:
        text = (label or "").strip().replace("\n", " ")
        if len(text) > 40:
            text = text[:39] + "…"
        self._set(self._RUN_IDX, t_("widget.run_active", label=text))

    def on_run_end(self) -> None:
        if not self._verdict_shown:
            self._set(self._VERDICT_IDX, t_("widget.verdict_no_check"))
        if not self._pinned:
            self.set_view("idle")

    @staticmethod
    def _skills_summary() -> str:
        return ActivityPanel._skill_catalog_summary()

    @staticmethod
    def _skill_catalog_summary() -> str:
        try:
            from argos import skills
            enabled = [s for s in skills.load_all() if s.enabled]
            if not enabled:
                return t_("widget.skills_none")
            return t_("widget.skills_available", n=len(enabled))
        except Exception:  # noqa: BLE001
            return "—"

    @staticmethod
    def _mcp_summary() -> str:
        try:
            import json

            from argos.mcp_native import resolve_config_path
            config_path = resolve_config_path()
            if not config_path.exists():
                return t_("widget.mcp_unconfigured")
            cfg = json.loads(config_path.read_text(encoding="utf-8")) or {}
            servers = cfg.get("servers") or {}
            enabled = [n for n, s in servers.items()
                       if isinstance(s, dict) and s.get("enabled", True)]
            return t_("widget.mcp_configured", n=len(enabled)) if enabled else t_("widget.mcp_unconfigured")
        except Exception:  # noqa: BLE001
            return t_("widget.mcp_unconfigured")

    def _sections(self) -> list[_Section]:
        return list(self.query(_Section))

    def _set(self, idx: int, body: "str | Text") -> None:
        self._sections()[idx].update(body)

    def _render_progress(self) -> None:
        if self._todos:
            self._set(self._PROGRESS_IDX, self._render_todos())
        else:
            self._set(self._PROGRESS_IDX, self._render_phases())

    def _render_phases(self) -> "str | Text":
        if not self._phases:
            return t_("widget.progress_pending")
        t = Text()
        for i, (p, e, s) in enumerate(self._phases):
            elapsed = "…" if s == "›" else (f"{e:.1f}s" if e else "—")
            line = f" {_PHASE_GLYPH.get(p, '◌')} {p:<7} {elapsed:>5} {s}"
            if i > 0:
                t.append("\n")
            if s == "›":
                t.append(line, style=_COL_INK_BRIGHT)
            elif s == "✓":
                t.append(line, style=_COL_INK_DIM)
            else:
                t.append(line, style=_COL_INK_FAINT)
        return t

    def _render_todos(self) -> "str | Text":
        done = sum(1 for todo in self._todos if todo.get("status") == "completed")
        t = Text()
        t.append(t_("widget.progress_todo", done=done, total=len(self._todos)))
        for todo in self._todos:
            status = todo.get("status", "pending")
            if status == "completed":
                t.append(f"\n ◕ {todo.get('content', '')}", style=_COL_INK_DIM)
            elif status == "in_progress":
                content = todo.get("activeForm") or todo.get("content", "")
                t.append(f"\n ◉ {content}", style=_COL_INK_BRIGHT)
            else:
                t.append(f"\n ◌ {todo.get('content', '')}", style=_COL_INK_FAINT)
        return t

    def on_phase(self, phase: str, actions: int) -> None:
        now = time.time()
        if self._phases:
            p, _, _ = self._phases[-1]
            self._phases[-1] = (p, max(0.0, now - self._phase_start), "✓")
        self._phase_start = now
        self._phases.append((phase, 0.0, "›"))
        self._render_progress()
        self._auto_view(phase)

    def on_plan(self, todos: list[dict]) -> None:
        self._todos = list(todos or [])
        self._render_progress()

    def on_receipt(self, action: str, sig: str = "") -> None:
        self._tool_counts[action] = self._tool_counts.get(action, 0) + 1
        tools = "\n".join(f"  {a} ×{n}" for a, n in self._tool_counts.items())
        self._set(self._TOOLS_IDX, t_("widget.tools_this_run", tools=tools) if tools else t_("widget.tools_zero"))
        sig_display = (sig[:8] if sig else "—")
        self._receipts.append((action, sig_display))
        self._set(
            self._RECEIPT_IDX,
            "\n".join(f"  {a}  {s}" for a, s in self._receipts[-6:]),
        )

    @staticmethod
    def _build_sparkline(values: list[int]) -> str:
        if not values:
            return ""
        _SPARK = "▁▂▃▄▅▆▇"
        max_v = max(values) or 1
        return "".join(_SPARK[min(6, int(v * 6 / max_v))] for v in values)

    @staticmethod
    def _fmt_tokens(n: int) -> str:
        return fmt_tokens(n)

    def on_cost(self, *, tokens_in: int, tokens_out: int, cost_usd: float | None,
                elapsed_s: float, cache_read: int = 0, tier_name: str = "") -> None:
        tier_tag = ""
        if tier_name:
            short = tier_name[:3]
            tier_tag = f" [{short}]"
        self._cache_history.append(cache_read)
        if cache_read > 0:
            self._cache_seen = True
        spark = self._build_sparkline(list(self._cache_history))
        cache_display = fmt_tokens(cache_read)
        t = Text()
        t.append(f"{fmt_token_flow(tokens_in, tokens_out)}{tier_tag}\n")
        if self._cache_seen:
            t.append(t_("widget.cache_hit_line", cache_read=cache_display, elapsed_s=elapsed_s))
            if spark:
                t.append(f"\ncache {spark} {cache_display} tok", style=_COL_CYAN)
        else:
            t.append(t_("widget.cache_idle_line", elapsed_s=elapsed_s))
        self._set(self._COST_IDX, t)

    def on_context(self, *, used: int, window: int) -> None:
        pct = 0 if not window else round(used * 100 / window)
        filled = min(10, max(0, round(pct / 10)))
        win = f"{window // 1000}k" if window else "?"
        badge = f"[ctx {used:,} / {win}]"
        t = Text()
        t.append("▓" * filled, style=_COL_EYE)
        t.append("░" * (10 - filled), style=_COL_INK_GHOST)
        t.append(f" {pct}%", style=_COL_INK_DIM)
        t.append(f"\n{badge}")
        if self._compaction_line:
            t.append(f"\n{self._compaction_line}")
        self._set(self._CTX_IDX, t)

    def on_verdict(self, verdict) -> None:
        cmd = getattr(verdict, "verify_cmd", None) or "—"
        detail = getattr(verdict, "detail", "") or ""
        status = getattr(verdict, "status", "?")
        self_verified = getattr(verdict, "self_verified", False)
        tag = " (self-verified)" if self_verified else ""
        _status_color = {
            "passed": _COL_PASS,
            "failed": _COL_FAIL,
            "unverifiable": _COL_UNVERIF,
        }
        if self_verified:
            status_color = _COL_PASS_WEAK
        else:
            status_color = _status_color.get(status, _COL_INK)
        t = Text()
        t.append(f"{status}{tag}", style=status_color)
        rest = f"\n{cmd}\n{detail}".rstrip()
        if rest.strip():
            t.append(rest)
        self._set(self._VERDICT_IDX, t)
        self._verdict_shown = True

    def on_hook_fired(self, ev: HookFired) -> None:
        self._hook_log.append(ev)
        lines = []
        for h in list(self._hook_log)[-5:]:
            cmd_short = h.command.split()[0] if h.command else "?"
            if h.timed_out:
                tag = f"timeout ({h.elapsed_ms}ms)"
            elif h.not_found:
                tag = "not found"
            elif h.success:
                tag = f"ok ({h.elapsed_ms}ms)"
            else:
                tag = f"fail (exit {h.returncode}, {h.elapsed_ms}ms)"
            lines.append(f" {h.event_name}:{cmd_short} {tag}")
        self._set(self._HOOK_IDX, "\n".join(lines) if lines else t_("widget.empty"))

    def on_lsp_server_event(self, ev: LspServerEvent) -> None:
        self._lsp_servers[ev.server_name] = ev.status
        lines: list[str] = []
        for name, status in self._lsp_servers.items():
            ms = ev.elapsed_ms if name == ev.server_name else 0
            if status == "spawn":
                tag = f"spawning ({ms}ms)" if ms else "spawning"
            elif status == "ready":
                tag = f"ready ({ms}ms)"
            elif status == "crash":
                tag = f"crash: {ev.error or '?'} ({ms}ms)"
            elif status == "disabled":
                tag = f"disabled: {ev.error or '?'}"
            elif status == "restart":
                tag = f"restarting ({ms}ms)"
            else:   # exit / unknown
                tag = status
            lines.append(f" · LSP {name}: {tag}")
        self._set(self._LSP_IDX, "\n".join(lines) if lines else t_("widget.empty"))

    def on_lsp_diagnostic_event(self, ev: LspDiagnosticEvent) -> None:
        prev = self._lsp_diag_cache.get(ev.uri)
        if prev == ev.count:
            return
        self._lsp_diag_cache[ev.uri] = ev.count

    def reset_run(self) -> None:
        self._verdict_shown = False
        self._phases.clear(); self._tool_counts.clear(); self._receipts.clear()
        self._todos.clear()
        self._hook_log.clear()
        self._lsp_servers.clear()
        self._lsp_diag_cache.clear()
        self._skill_runs.clear()
        self._approval_count = {"ok": 0, "ask": 0, "deny": 0}
        self._approval_log.clear()
        self._cache_history.clear()
        self._compaction_line = ""
        self._set(self._PROGRESS_IDX, t_("widget.progress_pending"))
        self._set(self._TOOLS_IDX, t_("widget.tools_zero"))
        self._set(self._RECEIPT_IDX, t_("widget.empty"))
        self._set(self._HOOK_IDX, t_("widget.empty"))
        self._set(self._LSP_IDX, t_("widget.empty"))
        self._set(self._SKILL_IDX, t_("widget.empty"))
        self._set(self._RUN_IDX, t_("widget.empty"))
        self._set(self._APPROVAL_IDX, t_("widget.empty"))
        self._set(self._VERDICT_IDX, t_("widget.empty"))
        self._set(self._CTX_IDX, t_("widget.empty"))

    def on_run_summary(self, *, active: int, paused: int, suspended: int, history: int) -> None:
        if active == 0 and paused == 0 and suspended == 0 and history == 0:
            self._set(self._RUN_IDX, t_("widget.empty"))
        else:
            self._set(
                self._RUN_IDX,
                f"⏵{active}  ⏸{paused}  ⏹{history}\n" + t_("widget.run_suspended", suspended=suspended),
            )

    def snapshot_text(self) -> str:
        return "\n".join(str(s.content) + " " + str(s.border_title) for s in self._sections())

    def _on_skill_run_start(self, ev: SkillRunStart) -> None:
        self._skill_runs.append(ev)
        self._refresh_skill_section()

    def _on_skill_run_end(self, ev: SkillRunEnd) -> None:
        self._skill_runs.append(ev)
        self._refresh_skill_section()

    def _refresh_skill_section(self) -> None:
        for s in self.query(_Section):
            if s.border_title == "Skill":
                s.update(self._skill_summary())
                return

    def _skill_summary(self) -> str:
        if not self._skill_runs:
            return t_("widget.empty")
        lines: list[str] = []
        pending_starts: dict[str, SkillRunStart] = {}
        for ev in self._skill_runs:
            if isinstance(ev, SkillRunStart):
                pending_starts[ev.skill_name] = ev
                timeout = ev.args.get("timeout", 60) if isinstance(ev.args, dict) else 60
                lines.append(f"{ev.skill_name}: started (timeout={timeout}s)")
            else:
                pending_starts.pop(ev.skill_name, None)
                dur = ev.duration_ms / 1000.0
                dur_str = f"{dur:.1f}s" if dur >= 1.0 else f"{int(ev.duration_ms)}ms"
                lines.append(
                    f"{ev.skill_name}: ended {ev.verdict} ({dur_str}, "
                    f"{ev.finding_count} finding{'s' if ev.finding_count != 1 else ''})"
                )
        return "\n".join(lines[-6:])

    def on_approval_decision(self, *, action: str, decision: str, trigger: str) -> None:
        bucket = {"approved": "ok", "denied": "deny", "asked": "ask"}.get(decision)
        if bucket is None:
            return
        self._approval_count[bucket] = self._approval_count.get(bucket, 0) + 1
        self._approval_log.append((action, decision, trigger))
        self._refresh_approval_section()

    def _refresh_approval_section(self) -> None:
        try:
            self._set(self._APPROVAL_IDX, self._approval_summary())
        except (IndexError, Exception):
            pass

    def _approval_summary(self) -> str:
        if not self._approval_log and not any(self._approval_count.values()):
            return t_("widget.empty")
        ok = self._approval_count.get("ok", 0)
        ask = self._approval_count.get("ask", 0)
        deny = self._approval_count.get("deny", 0)
        head = f"✓{ok}  ?{ask}  ✗{deny}"
        if not self._approval_log:
            return head
        lines = [head]
        for action, decision, trigger in list(self._approval_log)[-5:]:
            mark = {"approved": "✓", "denied": "✗", "asked": "?"}.get(decision, "·")
            lines.append(f" {mark} {action}  {trigger}")
        return "\n".join(lines)

    def on_compacted(self, before: int, after: int, reduction_pct: float) -> None:
        self._compaction_line = t_("widget.compacted_line", reduction_pct=reduction_pct, before=before, after=after)
        try:
            secs = self._sections()
            if secs and len(secs) > self._CTX_IDX:
                old = str(secs[self._CTX_IDX].content)
                lines = [l for l in old.splitlines() if not l.startswith("↯")]
                lines.append(self._compaction_line)
                self._set(self._CTX_IDX, "\n".join(lines))
        except Exception:  # noqa: BLE001
            pass

    def on_pruned(self, before: int, after: int, removed: int) -> None:
        self._compaction_line = t_("widget.pruned_line", removed=removed, before=before, after=after)
        try:
            secs = self._sections()
            if secs and len(secs) > self._CTX_IDX:
                old = str(secs[self._CTX_IDX].content)
                lines = [l for l in old.splitlines() if not l.startswith("↯")]
                lines.append(self._compaction_line)
                self._set(self._CTX_IDX, "\n".join(lines))
        except Exception:  # noqa: BLE001
            pass

    def on_memory_recall(self, hits: int) -> None:
        if hits > 0:
            self._set(self._RUN_IDX, t_("widget.memory_recall", hits=hits))
        else:
            self._set(self._RUN_IDX, t_("widget.empty"))
