"""右侧诚实活动栏(spec §ActivityPanel)。区块:模型/任务进度/工具/回执/Skills/MCP/成本+缓存/Hook/LSP。
诚实铁律:每块只反映真实数据;Skills/MCP/LSP 无真实内容时显示诚实空态('未加载'/'0 已连接'/'(无)')。"""
from __future__ import annotations

import time
from collections import deque

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.widgets import Static

from argos_agent.hooks.events import HookFired
from argos_agent.lsp.events import LspServerEvent, LspDiagnosticEvent
from argos_agent.skills_runtime.events import SkillRunStart, SkillRunEnd

_PHASE_GLYPH = {"plan": "◇", "act": "✦", "verify": "✦", "report": "◇"}


class _Section(Static):
    # 每块自带"格子"观感:顶部 $text-muted 分隔线(可见,非近黑 $panel) + 嵌在线上的橙色粗体
    # 标题 + 块间留 1 行空白。此前各块紧贴、分隔线用近黑 $panel 看不见 → 用户体感"全挤一起"。
    DEFAULT_CSS = """
    _Section {
        height: auto;
        padding: 0 1;
        margin: 0 0 1 0;
        border-top: solid $foreground-darken-3;
        border-title-color: $accent;
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
    # overflow-y: auto → 内容超出可视高度时自动出竖向滚动条(滚轮+拖拽都恢复可用);
    # 此前继承 Vertical 默认 overflow-y: hidden,区块超高即被裁且完全滚不动。
    # border-title-color 在 _Section 显式给 $foreground(亮白)——默认是透明(alpha=0)看不见。
    DEFAULT_CSS = """
    ActivityPanel { width: 34; border-left: solid $panel; padding: 1 0 0 0; overflow-y: auto; scrollbar-size-vertical: 1; }
    """
    def __init__(self, *, model_label: str = "—", tier: str = "—", **kwargs) -> None:
        super().__init__(**kwargs)
        self._model_label = model_label
        self._tier = tier
        self._phases: list[tuple[str, float, str]] = []   # (phase, elapsed, status)
        self._phase_start = 0.0
        self._tool_counts: dict[str, int] = {}
        self._receipts: list[str] = []
        self._todos: list[dict] = []   # 真 TODO 拆解(update_plan);非空时"任务进度"区改渲染它
        self._hook_log: deque[HookFired] = deque(maxlen=50)   # spec §2.4 最多 50
        # LSP 状态(spec 2026-06-06 §2.7):server_name → 最新 status(spawn/ready/crash/disabled)
        # + uri → 最近 count(变化检测 dedup)
        self._lsp_servers: dict[str, str] = {}
        self._lsp_diag_cache: dict[str, int] = {}   # uri → 最近 count
        # Skill run 状态(spec §2.6 / §2.7):新 idx 10 区段
        # 存最近 N 条 SkillRunStart / SkillRunEnd,渲染时按 start/end 配对
        self._skill_runs: deque[SkillRunStart | SkillRunEnd] = deque(maxlen=20)

    def compose(self) -> ComposeResult:
        yield _Section("模型", self._model_label)
        yield _Section("任务进度", "(待开始)", )  # id 设下方
        yield _Section("工具", "本轮 0 调用")
        yield _Section("回执(已签名)", "—")
        yield _Section("Run", "(无)")   # ← 新增 idx 4:daemon 模式 run 概览
        yield _Section("Skill Catalog", self._skill_catalog_summary())  # ← 重命名(原 Skills)
        yield _Section("MCP", self._mcp_summary())
        yield _Section("成本 + 缓存", "↑0 ↓0  $0.000\n缓存命中 0 tok  0.0s")
        yield _Section("上下文", "")
        yield _Section("Hook", "(无)")
        yield _Section("LSP", "(无)")
        yield _Section("Skill", self._skill_summary())  # ← 新增 idx 10(singular,运行时执行)

    @staticmethod
    def _skills_summary() -> str:
        """向后兼容:旧名 = 新名(spec §2.6 重命名后原方法保留作 alias)。"""
        return ActivityPanel._skill_catalog_summary()

    @staticmethod
    def _skill_catalog_summary() -> str:
        """'Skill Catalog' 段(idx 4):列按任务召回的 markdown 库技能(skills.py)。
        与 'Skill' 段(idx 10)区分——后者显示运行时执行的 analysis skill。"""
        try:
            from argos_agent import skills
            enabled = [s for s in skills.load_all() if s.enabled]
            if not enabled:
                return "无可用"
            return f"{len(enabled)} 个可用(按任务召回)"
        except Exception:  # noqa: BLE001
            return "—"

    @staticmethod
    def _mcp_summary() -> str:
        """诚实显示 MCP:读 ~/.argos/mcp.json 里配置的(启用)server 数。默认零预配 → '未配置'。
        '已配置' 不等于 '已连接'(连接在后台异步预热);此处只如实报配置,不谎报连接态。"""
        try:
            import json

            from argos_agent.mcp_native import CONFIG_PATH
            if not CONFIG_PATH.exists():
                return "未配置"
            cfg = json.loads(CONFIG_PATH.read_text(encoding="utf-8")) or {}
            servers = cfg.get("servers") or {}
            enabled = [n for n, s in servers.items()
                       if isinstance(s, dict) and s.get("enabled", True)]
            return f"{len(enabled)} 个已配置" if enabled else "未配置"
        except Exception:  # noqa: BLE001
            return "未配置"

    def _sections(self) -> list[_Section]:
        return list(self.query(_Section))

    def _set(self, idx: int, body: str) -> None:
        self._sections()[idx].update(body)

    # ── 事件入口(app._apply_event 调) ──────────────────────────────
    def _render_progress(self) -> None:
        """"任务进度"区(idx 1):有真 TODO 拆解时渲染 todo,否则退回 4 阶段计时。"""
        if self._todos:
            self._set(1, self._render_todos())
        else:
            self._set(1, self._render_phases())

    def _render_phases(self) -> str:
        lines = []
        for p, e, s in self._phases:
            # 进行中(▶,elapsed 还是 0.0)显 …;完成且无耗时显 —;否则显真实耗时。
            elapsed = "…" if s == "▶" else (f"{e:.1f}s" if e else "—")
            lines.append(f" {_PHASE_GLYPH.get(p, '◇')} {p:<7} {elapsed:>5} {s}")
        return "\n".join(lines) if lines else "(待开始)"

    def _render_todos(self) -> str:
        done = sum(1 for t in self._todos if t.get("status") == "completed")
        lines = [f"进度 {done}/{len(self._todos)}"]
        for t in self._todos:
            status = t.get("status", "pending")
            if status == "completed":
                lines.append(f" ✅ {t.get('content', '')}")
            elif status == "in_progress":
                # 进行中显 activeForm(无则退回 content)。
                lines.append(f" 🔧 {t.get('activeForm') or t.get('content', '')}")
            else:
                lines.append(f" ⬜ {t.get('content', '')}")
        return "\n".join(lines)

    def on_phase(self, phase: str, actions: int) -> None:
        now = time.time()
        if self._phases:
            p, _, _ = self._phases[-1]
            self._phases[-1] = (p, max(0.0, now - self._phase_start), "✓")
        self._phase_start = now
        self._phases.append((phase, 0.0, "▶"))
        self._render_progress()

    def on_plan(self, todos: list[dict]) -> None:
        """真 TODO 拆解(update_plan)到达 →"任务进度"区改渲染子任务进度(替代 4 阶段计时)。"""
        self._todos = list(todos or [])
        self._render_progress()

    def on_receipt(self, action: str) -> None:
        self._tool_counts[action] = self._tool_counts.get(action, 0) + 1
        tools = "\n".join(f"  {a} ×{n}" for a, n in self._tool_counts.items())
        self._set(2, f"本轮调用:\n{tools}" if tools else "本轮 0 调用")
        self._receipts.append(action)
        self._set(3, "\n".join(f"🧾 {a}" for a in self._receipts[-6:]))

    def on_cost(self, *, tokens_in: int, tokens_out: int, cost_usd: float | None,
                elapsed_s: float, cache_read: int = 0) -> None:
        cost = "$(N/A)" if cost_usd is None else f"${cost_usd:.3f}"
        self._set(7, f"↑{tokens_in} ↓{tokens_out}  {cost}\n"
                     f"缓存命中 {cache_read} tok  {elapsed_s:.1f}s")

    def on_context(self, *, used: int, window: int) -> None:
        """上下文窗口用量(当前窗口输入侧 token / 上限)。10 格进度条 + 百分比;
        口径对齐 Claude Code:used 是【当前窗口占用】(input+cache),非会话累计成本。"""
        pct = 0 if not window else round(used * 100 / window)
        filled = min(10, max(0, round(pct / 10)))
        bar = "▓" * filled + "░" * (10 - filled)
        win = f"{window // 1000}k" if window else "?"
        self._set(8, f"{self._model_label} · {win}\n{bar} {pct}%")

    def on_hook_fired(self, ev: HookFired) -> None:
        """单条 hook 触发结果(activity panel "Hook" 区段)。
        3 态:ok(dim) / fail(red 标记) / timeout(red 标记)。"""
        self._hook_log.append(ev)
        # 渲染最近 5 条(避免区段超高);每条:event + command + 状态 + 耗时
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
        self._set(9, "\n".join(lines) if lines else "(无)")

    # ── LSP(spec §2.7):4 态 + 变化检测 dedup ─────────────────────────
    # LSP 段 idx = 10(在 Hook 段后,见 compose 顺序)
    _LSP_IDX: int = 10

    def on_lsp_server_event(self, ev: LspServerEvent) -> None:
        """单条 LSP server 生命周期事件(活动栏 "LSP" 区段)。
        4 态:spawn / ready / crash / disabled(各显一行,带 elapsed_ms)。"""
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
        self._set(self._LSP_IDX, "\n".join(lines) if lines else "(无)")

    def on_lsp_diagnostic_event(self, ev: LspDiagnosticEvent) -> None:
        """诊断推送事件:仅当 count 变化时更新活动栏(spec §2.7 dedup)。"""
        prev = self._lsp_diag_cache.get(ev.uri)
        if prev == ev.count:
            return   # dedup:不重渲
        self._lsp_diag_cache[ev.uri] = ev.count

    def reset_run(self) -> None:
        self._phases.clear(); self._tool_counts.clear(); self._receipts.clear()
        self._todos.clear()
        self._hook_log.clear()
        self._lsp_servers.clear()
        self._lsp_diag_cache.clear()
        self._skill_runs.clear()
        self._set(1, "(待开始)"); self._set(2, "本轮 0 调用"); self._set(3, "—")
        self._set(9, "(无)"); self._set(self._LSP_IDX, "(无)")
        self._set(self._SKILL_IDX, "(无)")
        self._set(self._RUN_IDX, "(无)")

    # ── Run 段(spec §2.6 b/c 段)──────────────────────────────────
    _RUN_IDX: int = 4   # 任务进度后,Skill Catalog 前

    def on_run_summary(self, *, active: int, paused: int, suspended: int, history: int) -> None:
        """渲染 'Run' 区段:⏵N active / ⏸N paused / ⏹N history。

        active = running;paused = paused;
        history = suspended + completed + failed + cancelled;
        走 state count → 不存 id 列表(本期单 TUI 限定)。"""
        if active == 0 and paused == 0 and suspended == 0 and history == 0:
            self._set(self._RUN_IDX, "(无)")
        else:
            self._set(
                self._RUN_IDX,
                f"⏵{active}  ⏸{paused}  ⏹{history}\n(suspended {suspended})",
            )

    def snapshot_text(self) -> str:
        # Textual 8.2.7 的 Static 用 .content 暴露当前正文(随 .update() 刷新),不再有 .renderable。
        return "\n".join(str(s.content) + " " + str(s.border_title) for s in self._sections())

    # ── Skill run(新 idx 11 区段)────────────────────────────────────
    _SKILL_IDX: int = 11

    def _on_skill_run_start(self, ev: SkillRunStart) -> None:
        """收到 SkillRunStart → 入 deque + 触发区段刷新。"""
        self._skill_runs.append(ev)
        self._refresh_skill_section()

    def _on_skill_run_end(self, ev: SkillRunEnd) -> None:
        """收到 SkillRunEnd → 入 deque + 触发区段刷新。"""
        self._skill_runs.append(ev)
        self._refresh_skill_section()

    def _refresh_skill_section(self) -> None:
        """刷新 'Skill' 区段(运行时执行):按 start/end 配对渲染。"""
        # 找 compose() 产出的 _Section("Skill") 节点并 update
        for s in self.query(_Section):
            if s.border_title == "Skill":
                s.update(self._skill_summary())
                return

    def _skill_summary(self) -> str:
        """'Skill' 区段(singular)渲染:start + end 配对成行(对位 Hook 区段)."""
        if not self._skill_runs:
            return "(无)"
        # 配对 start/end(简单按出现顺序;实际生产可按 run_id)
        lines: list[str] = []
        pending_starts: dict[str, SkillRunStart] = {}
        for ev in self._skill_runs:
            if isinstance(ev, SkillRunStart):
                pending_starts[ev.skill_name] = ev
                timeout = ev.args.get("timeout", 60) if isinstance(ev.args, dict) else 60
                lines.append(f"{ev.skill_name}: started (timeout={timeout}s)")
            else:
                s = pending_starts.pop(ev.skill_name, None)
                dur = ev.duration_ms / 1000.0
                dur_str = f"{dur:.1f}s" if dur >= 1.0 else f"{int(ev.duration_ms)}ms"
                lines.append(
                    f"{ev.skill_name}: ended {ev.verdict} ({dur_str}, "
                    f"{ev.finding_count} finding{'s' if ev.finding_count != 1 else ''})"
                )
        return "\n".join(lines[-6:])   # 最多 6 行
