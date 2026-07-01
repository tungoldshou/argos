"""右侧诚实活动栏(TUI v2 spec §5:智能切视图)。

数据层不变:每块只反映真实数据;Skills/MCP/LSP 无真实内容时显示诚实空态
('未加载'/'0 已连接'/'(无)')。渲染层改为 4 视图按阶段自动切换(用户拍板"智能切"):
  idle   → 模型 / Run / Skill Catalog / MCP / 上轮 Verdict
  plan   → 任务进度(TODO 或 4 阶段计时)
  act    → 任务进度 / 工具 / 回执 / Hook / LSP / Skill / Approval
  verify → 任务进度 / Approval / Verdict
成本+缓存 与 上下文 两块所有视图常驻(钱与上下文任何时刻可见)。
实现:全部 _Section 常驻 DOM,按视图切 display —— snapshot_text() 聚合全部数据
(不只当前视图),/cost 回显与测试断言不受视图切换影响。Ctrl+O(app 绑定)cycle_view 手动 pin。
"""
from __future__ import annotations

import time
from collections import deque

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Vertical
from textual.widgets import Static

# Rich Text hex 颜色常量(与 theme.py token 一一对应)
# DEFAULT_CSS 用 $token 名;Rich Text 渲染用以下 hex 常量(Rich 不解析 $token)
_COL_PASS       = "#9ECE6A"  # $pass:       verdict passed(绿)
_COL_PASS_WEAK  = "#73A857"  # $pass-weak:  self-verified 弱通过
_COL_FAIL       = "#F7768E"  # $fail:       verdict failed(红)
_COL_UNVERIF    = "#FF9E64"  # $unverif:    verdict unverifiable(橙)
_COL_CYAN       = "#7DCFFF"  # $cyan:       缓存命中 sparkline(冷色=省钱)
_COL_EYE        = "#D9A85C"  # $eye:        进度条填充段(金)
_COL_INK_BRIGHT = "#ECEEF5"  # $ink-bright: 进行中条目
_COL_INK        = "#C8CCDA"  # $ink:        正文
_COL_INK_DIM    = "#7E869C"  # $ink-dim:    完成条目 / 百分比
_COL_INK_FAINT  = "#6B7494"  # $ink-faint:  待办条目(finding #27 升对比度)
_COL_INK_GHOST  = "#3A4055"  # $ink-ghost:  进度条空段

from argos.i18n import t as t_
from argos.tui.widgets._fmt import fmt_token_flow, fmt_tokens
from argos.hooks.events import HookFired
from argos.lsp.events import LspServerEvent, LspDiagnosticEvent
from argos.skills_runtime.events import SkillRunStart, SkillRunEnd

# v3 字形词典(spec §3.1):plan=◔ act=◉ verify=❂ report=◕
_PHASE_GLYPH = {"plan": "◔", "act": "◉", "verify": "❂", "report": "◕"}

# 视图顺序(cycle_view 循环序);"auto" 不在列表里,是模式而非视图。
_VIEWS = ("idle", "plan", "act", "verify")


class _Section(Static):
    # 每块自带"格子"观感:顶部 $text-muted 分隔线(可见,非近黑 $panel) + 嵌在线上的橙色粗体
    # 标题 + 块间留 1 行空白。
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
        # markup=False:区块正文含模型给的 TODO 文案 / 工具名等任意文本,可能带 `[...]`,
        # 不可被当 Rich markup 解析(防崩);update() 沿用此 markup 设置。
        super().__init__(body, markup=False)
        self.border_title = title


class ActivityPanel(Vertical):
    # overflow-y: auto → 内容超出可视高度时自动出竖向滚动条。
    DEFAULT_CSS = """
    ActivityPanel { width: 34; background: $well; padding: 1 0 0 0; overflow-y: auto; scrollbar-size-vertical: 1; }
    ActivityPanel #view-header { color: $eye-soft; text-style: bold; padding: 0 1; margin: 0 0 1 0; }
    """

    # ── 区段索引(compose 顺序的单一真源)───────────────────────────
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
    _COST_IDX = 12      # 常驻 footer
    _CTX_IDX = 13       # 常驻 footer

    # 视图 → 可见区段(footer 两块所有视图常驻,单列于 _FOOTER)
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
        self._todos: list[dict] = []   # 真 TODO 拆解(update_plan);非空时"任务进度"区改渲染它
        self._hook_log: deque[HookFired] = deque(maxlen=50)   # spec §2.4 最多 50
        self._lsp_servers: dict[str, str] = {}
        self._lsp_diag_cache: dict[str, int] = {}   # uri → 最近 count
        self._skill_runs: deque[SkillRunStart | SkillRunEnd] = deque(maxlen=20)
        # Approval 段:3 类决策计数器 + 最近 N 条 log。
        self._approval_count: dict[str, int] = {"ok": 0, "ask": 0, "deny": 0}
        self._approval_log: deque[tuple[str, str, str]] = deque(maxlen=10)
        # 缓存 sparkline 历史(最近 8 次 cache_read 值)
        self._cache_history: deque[int] = deque(maxlen=8)
        # 是否【曾】见过真实缓存命中(>0)。非缓存 provider(如不报 cache 的 OpenAI-compat 端点)
        # 永远 cache_read=0 → 不显误导性的 "cache hit 0",改中性行;一旦真见过缓存就切回完整行。
        # provider 级状态,跨轮粘性(reset_run 不清)。
        self._cache_seen: bool = False
        # 压缩/修剪 信息(上下文区追加行)
        self._compaction_line: str = ""
        # ── 智能切状态(TUI v2)─────────────────────────────────
        self._view: str = "idle"          # 当前视图
        self._pinned: bool = False        # True = 用户 Ctrl+O 手动钉住,phase 不再自动切
        self._verdict_shown: bool = False  # 本轮是否投过 VerifyVerdict(收尾给"只读·无机检"诚实兜底)

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

    # ── 智能切(TUI v2 spec §5)─────────────────────────────────────
    def _header_text(self) -> str:
        # v3 spec §4.8:pinned 标记用 * 而非 emoji
        pin = " *" if self._pinned else ""
        return t_("widget.view_header", view=self._view, pin=pin)

    def _apply_view(self) -> None:
        """按当前视图切区段可见性(数据照常更新,只动 display)。"""
        visible = self._VIEW_SECTIONS.get(self._view, frozenset()) | self._FOOTER
        for i, sec in enumerate(self._sections()):
            sec.display = i in visible
        try:
            self.query_one("#view-header", Static).update(self._header_text())
        except Exception:  # noqa: BLE001 — 未 mount(测试直构)时静默
            pass

    def set_view(self, view: str, *, pinned: bool | None = None) -> None:
        if view not in _VIEWS:
            return  # 诚实:未知视图不假装切换
        self._view = view
        if pinned is not None:
            self._pinned = pinned
        self._apply_view()

    def cycle_view(self) -> str:
        """Ctrl+O:auto → idle → plan → act → verify → auto。返回当前模式(显示用)。"""
        if not self._pinned:
            self._pinned = True
            self.set_view(_VIEWS[0])
            return _VIEWS[0]
        idx = _VIEWS.index(self._view) if self._view in _VIEWS else 0
        if idx + 1 < len(_VIEWS):
            self.set_view(_VIEWS[idx + 1])
            return _VIEWS[idx + 1]
        self._pinned = False           # 走完一圈回 auto
        self._apply_view()
        return "auto"

    def _auto_view(self, phase: str) -> None:
        if self._pinned:
            return
        view = {"plan": "plan", "act": "act", "verify": "verify", "report": "verify"}.get(phase)
        if view:
            self.set_view(view)

    def on_run_active(self, label: str) -> None:
        """run 起手:Run 段显当前活跃 run(取代旧版整轮显 '(none)')。
        label 过长截断(右栏窄)。on_memory_recall 命中时会用召回信息覆盖,二者都是 run 相关信息。"""
        text = (label or "").strip().replace("\n", " ")
        if len(text) > 40:
            text = text[:39] + "…"
        self._set(self._RUN_IDX, t_("widget.run_active", label=text))

    def on_run_end(self) -> None:
        """run 收尾:auto 模式回 idle 视图(verdict/成本仍可见)。
        本轮没投过 VerifyVerdict(纯对话/只读/出错于 verify 前)→ Verdict 段给诚实兜底文案,
        而非误导性的 '(none)'(诚实铁律:不机检就说没机检,绝不冒充通过)。"""
        if not self._verdict_shown:
            self._set(self._VERDICT_IDX, t_("widget.verdict_no_check"))
        if not self._pinned:
            self.set_view("idle")

    # ── 数据摘要(诚实空态)──────────────────────────────────────────
    @staticmethod
    def _skills_summary() -> str:
        """向后兼容:旧名 = 新名(spec §2.6 重命名后原方法保留作 alias)。"""
        return ActivityPanel._skill_catalog_summary()

    @staticmethod
    def _skill_catalog_summary() -> str:
        """'Skill Catalog' 段:列按任务召回的 markdown 库技能(skills.py)。"""
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
        """诚实显示 MCP:读 ~/.argos/mcp.json 里配置的(启用)server 数。默认零预配 → '未配置'。
        '已配置' 不等于 '已连接'(连接在后台异步预热);此处只如实报配置,不谎报连接态。"""
        try:
            import json

            from argos.mcp_native import CONFIG_PATH
            if not CONFIG_PATH.exists():
                return t_("widget.mcp_unconfigured")
            cfg = json.loads(CONFIG_PATH.read_text(encoding="utf-8")) or {}
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

    # ── 事件入口(app._apply_event 调;签名全部保持)───────────────────
    def _render_progress(self) -> None:
        """"任务进度"区:有真 TODO 拆解时渲染 todo,否则退回 4 阶段计时。"""
        if self._todos:
            self._set(self._PROGRESS_IDX, self._render_todos())
        else:
            self._set(self._PROGRESS_IDX, self._render_phases())

    def _render_phases(self) -> "str | Text":
        # [FIX LOW] 进行中→$ink-bright, 完成→$ink-dim, 待办→$ink-faint
        if not self._phases:
            return t_("widget.progress_pending")
        t = Text()
        for i, (p, e, s) in enumerate(self._phases):
            # 进行中(›,elapsed 还是 0.0)显 …;完成且无耗时显 —;否则显真实耗时。
            elapsed = "…" if s == "›" else (f"{e:.1f}s" if e else "—")
            line = f" {_PHASE_GLYPH.get(p, '◌')} {p:<7} {elapsed:>5} {s}"
            if i > 0:
                t.append("\n")
            if s == "›":
                # 进行中
                t.append(line, style=_COL_INK_BRIGHT)
            elif s == "✓":
                # 已完成
                t.append(line, style=_COL_INK_DIM)
            else:
                # 待办/其他
                t.append(line, style=_COL_INK_FAINT)
        return t

    def _render_todos(self) -> "str | Text":
        # v3:emoji 已处决,改用字形词典字符(spec §3.3)
        # [FIX LOW] 进行中→$ink-bright, 完成→$ink-dim, 待办→$ink-faint
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
        self._auto_view(phase)   # 智能切:阶段驱动视图

    def on_plan(self, todos: list[dict]) -> None:
        """真 TODO 拆解(update_plan)到达 →"任务进度"区改渲染子任务进度。"""
        self._todos = list(todos or [])
        self._render_progress()

    def on_receipt(self, action: str, sig: str = "") -> None:
        """记录一条工具回执。sig 为 HMAC 签名前 8 字符截断(finding #6:使签名声明可伪证)。

        sig 为空字符串时显示 '—'(诚实占位,而非假装已签名)。
        """
        self._tool_counts[action] = self._tool_counts.get(action, 0) + 1
        tools = "\n".join(f"  {a} ×{n}" for a, n in self._tool_counts.items())
        self._set(self._TOOLS_IDX, t_("widget.tools_this_run", tools=tools) if tools else t_("widget.tools_zero"))
        # _receipts 存 (action, sig_display) 对
        sig_display = (sig[:8] if sig else "—")
        self._receipts.append((action, sig_display))
        # 回执区段:每行「action  sig[:8]」,最多显示最近 6 条(finding #6)
        self._set(
            self._RECEIPT_IDX,
            "\n".join(f"  {a}  {s}" for a, s in self._receipts[-6:]),
        )

    # ── 缓存 sparkline 辅助(spec §4.8 a 机会点④)─────────────────────────
    @staticmethod
    def _build_sparkline(values: list[int]) -> str:
        """将整数序列映射到 ▁▂▃▄▅▆▇ 字符。非空序列返回 sparkline 字串,空序列返回 ''。"""
        if not values:
            return ""
        _SPARK = "▁▂▃▄▅▆▇"
        max_v = max(values) or 1
        return "".join(_SPARK[min(6, int(v * 6 / max_v))] for v in values)

    @staticmethod
    def _fmt_tokens(n: int) -> str:
        """千分缩写:≥1000 → '{n/1000:.1f}k',否则原整数字串。委托共享 _fmt(单一真源)。"""
        return fmt_tokens(n)

    def on_cost(self, *, tokens_in: int, tokens_out: int, cost_usd: float | None,
                elapsed_s: float, cache_read: int = 0, tier_name: str = "") -> None:
        # 花费($)显示已移除(不再配价格);cost_usd 形参保留(喂数据方不变),只是不再渲染。
        # #11 per-task routing:每步用量归属具体 profile(3 字母短标签,spec D15)
        tier_tag = ""
        if tier_name:
            short = tier_name[:3]
            tier_tag = f" [{short}]"
        # 缓存 sparkline(机会点④):记录本次 cache_read 进历史,渲染 ▁▂▃▄▅▆▇
        self._cache_history.append(cache_read)
        if cache_read > 0:
            self._cache_seen = True
        spark = self._build_sparkline(list(self._cache_history))
        # token:↑输入 ↓输出 + tok 单位(共享 _fmt,与 StatusBar 同一真源)
        # [FIX MEDIUM] cache sparkline 整行染 $cyan(冷色=省钱语义)
        t = Text()
        t.append(f"{fmt_token_flow(tokens_in, tokens_out)}{tier_tag}\n")
        if self._cache_seen:
            t.append(t_("widget.cache_hit_line", cache_read=cache_read, elapsed_s=elapsed_s))
            if spark:
                t.append(f"\ncache {spark} {cache_read}", style=_COL_CYAN)
        else:
            # 从未见过缓存命中:不显 "cache hit 0"(易被误读为故障),只显中性行 + 耗时。
            t.append(t_("widget.cache_idle_line", elapsed_s=elapsed_s))
        self._set(self._COST_IDX, t)

    def on_context(self, *, used: int, window: int) -> None:
        """上下文窗口用量。10 格进度条 + 百分比 + badge `[ctx N / Wk]`(spec §10.3);
        口径对齐 Claude Code:used 是【当前窗口占用】(input+cache),非会话累计成本。

        去冗余(2026-06-22):此前三行重复 —— model·window 头行(model 与 Model 段重复)、
        进度条旁独立 % 与 badge 内 % 重复、window 同时以 '1000k' 与 '1,000,000' 两形态出现。
        现:pct 只在进度条上一次;window 只以人类可读 '{win}' 在 badge 出现一次;
        绝对用量(精确)在 badge;model 不再于此重复(已在顶部 Model 段)。"""
        pct = 0 if not window else round(used * 100 / window)
        filled = min(10, max(0, round(pct / 10)))
        win = f"{window // 1000}k" if window else "?"
        badge = f"[ctx {used:,} / {win}]"
        # [FIX MEDIUM] 进度条填充段染 $eye、空段染 $ink-ghost、百分比染 $ink-dim
        t = Text()
        t.append("▓" * filled, style=_COL_EYE)
        t.append("░" * (10 - filled), style=_COL_INK_GHOST)
        t.append(f" {pct}%", style=_COL_INK_DIM)
        t.append(f"\n{badge}")
        # 若有压缩/修剪行,追加(spec §4.8 a 机会点①)
        if self._compaction_line:
            t.append(f"\n{self._compaction_line}")
        self._set(self._CTX_IDX, t)

    def on_verdict(self, verdict) -> None:
        """VerifyVerdict 到达 → 'Verdict' 区段(verify/idle 视图可见)。
        三态铁律:status 原样显示;self-verified 显式标注,绝不冒充用户级 verify。
        [FIX HIGH] 按状态注入 token 颜色:passed→$pass, failed→$fail,
                   unverifiable→$unverif, self-verified→$pass-weak。
        """
        cmd = getattr(verdict, "verify_cmd", None) or "—"
        detail = getattr(verdict, "detail", "") or ""
        status = getattr(verdict, "status", "?")
        self_verified = getattr(verdict, "self_verified", False)
        tag = " (self-verified)" if self_verified else ""
        # 状态 → 颜色映射(诚实三态铁律)
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
        self._verdict_shown = True   # 本轮已机检 → on_run_end 不再覆盖兜底文案

    def on_hook_fired(self, ev: HookFired) -> None:
        """单条 hook 触发结果。3 态:ok(dim) / fail(red 标记) / timeout(red 标记)。"""
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

    # ── LSP(spec §2.7):4 态 + 变化检测 dedup ─────────────────────────
    def on_lsp_server_event(self, ev: LspServerEvent) -> None:
        """单条 LSP server 生命周期事件。4 态:spawn / ready / crash / disabled。"""
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
        """诊断推送事件:仅当 count 变化时更新活动栏(spec §2.7 dedup)。"""
        prev = self._lsp_diag_cache.get(ev.uri)
        if prev == ev.count:
            return   # dedup:不重渲
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
        # v3 空态:一律 ◌ (无) + $ink-faint(spec §4.8)
        self._set(self._PROGRESS_IDX, t_("widget.progress_pending"))
        self._set(self._TOOLS_IDX, t_("widget.tools_zero"))
        self._set(self._RECEIPT_IDX, t_("widget.empty"))
        self._set(self._HOOK_IDX, t_("widget.empty"))
        self._set(self._LSP_IDX, t_("widget.empty"))
        self._set(self._SKILL_IDX, t_("widget.empty"))
        self._set(self._RUN_IDX, t_("widget.empty"))
        self._set(self._APPROVAL_IDX, t_("widget.empty"))
        self._set(self._VERDICT_IDX, t_("widget.empty"))
        # footer:Context 段也要复位,否则上一个 run 的 context 进度条残留到下一个 run。
        self._set(self._CTX_IDX, t_("widget.empty"))

    # ── Run 段(spec §2.6 b/c 段)──────────────────────────────────
    def on_run_summary(self, *, active: int, paused: int, suspended: int, history: int) -> None:
        """渲染 'Run' 区段:⏵N active / ⏸N paused / ⏹N history。"""
        if active == 0 and paused == 0 and suspended == 0 and history == 0:
            self._set(self._RUN_IDX, t_("widget.empty"))
        else:
            self._set(
                self._RUN_IDX,
                f"⏵{active}  ⏸{paused}  ⏹{history}\n" + t_("widget.run_suspended", suspended=suspended),
            )

    def snapshot_text(self) -> str:
        # 聚合【全部】区段(含当前视图隐藏的)——/cost 回显与测试断言不受视图切换影响。
        return "\n".join(str(s.content) + " " + str(s.border_title) for s in self._sections())

    # ── Skill run 区段────────────────────────────────────────────
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
        """'Skill' 区段(singular)渲染:start + end 配对成行(对位 Hook 区段)."""
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
        return "\n".join(lines[-6:])   # 最多 6 行

    # ── Approval 段:3 类决策计数 + log ────────────────────────────
    def on_approval_decision(self, *, action: str, decision: str, trigger: str) -> None:
        """收到一次审批结论 → 计数器 +1 + 入 log + 刷新区段。

        decision ∈ {approved, denied, asked};对位 _approval_count 三键 {ok, ask, deny}。"""
        bucket = {"approved": "ok", "denied": "deny", "asked": "ask"}.get(decision)
        if bucket is None:
            return  # 非法值忽略(诚实:坏数据不假装计入)
        self._approval_count[bucket] = self._approval_count.get(bucket, 0) + 1
        self._approval_log.append((action, decision, trigger))
        self._refresh_approval_section()

    def _refresh_approval_section(self) -> None:
        """刷新 'Approval' 区段:首行计数器 + 最近 5 条 log。"""
        try:
            self._set(self._APPROVAL_IDX, self._approval_summary())
        except (IndexError, Exception):
            # 未 mount 时(测试直接构造)_sections() 为空,update 抛 → 忽略,数据已记录。
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

    # ── 纯新增方法(spec §4.8 c):on_compacted / on_pruned / on_memory_recall ────
    def on_compacted(self, before: int, after: int, reduction_pct: float) -> None:
        """压缩事件(CompactedEvent):上下文区追加 ↯ 压缩行(spec §4.8 a 机会点①)。

        签名:on_compacted(before, after, reduction_pct) — P9 接线约定。
        """
        self._compaction_line = t_("widget.compacted_line", reduction_pct=reduction_pct, before=before, after=after)
        # 若上下文区已有内容,立即刷新;否则等下次 on_context 调用时追加。
        try:
            secs = self._sections()
            if secs and len(secs) > self._CTX_IDX:
                old = str(secs[self._CTX_IDX].content)
                # 替换或追加 ↯ 行
                lines = [l for l in old.splitlines() if not l.startswith("↯")]
                lines.append(self._compaction_line)
                self._set(self._CTX_IDX, "\n".join(lines))
        except Exception:  # noqa: BLE001
            pass  # 未 mount 时静默

    def on_pruned(self, before: int, after: int, removed: int) -> None:
        """修剪事件(PrunedEvent):上下文区追加修剪行(spec §4.8 a 机会点①)。

        签名:on_pruned(before, after, removed) — P9 接线约定。
        """
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
        """记忆召回提示(spec §4.8 a 机会点⑤):Run 区段显 ◌ 召回 N 条。

        签名:on_memory_recall(hits) — P9 接线约定。
        """
        if hits > 0:
            self._set(self._RUN_IDX, t_("widget.memory_recall", hits=hits))
        else:
            self._set(self._RUN_IDX, t_("widget.empty"))
