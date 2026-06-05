"""右侧诚实活动栏(spec §ActivityPanel)。区块:模型/任务进度/工具/回执/Skills/MCP/成本+缓存/Hook。
诚实铁律:每块只反映真实数据;Skills/MCP 无真实内容时显示诚实空态('未加载'/'0 已连接')。"""
from __future__ import annotations

import time
from collections import deque

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.widgets import Static

from argos_agent.hooks.events import HookFired

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

    def compose(self) -> ComposeResult:
        yield _Section("模型", self._model_label)
        yield _Section("任务进度", "(待开始)", )  # id 设下方
        yield _Section("工具", "本轮 0 调用")
        yield _Section("回执(已签名)", "—")
        yield _Section("Skills", self._skills_summary())
        yield _Section("MCP", self._mcp_summary())
        yield _Section("成本 + 缓存", "↑0 ↓0  $0.000\n缓存命中 0 tok  0.0s")
        yield _Section("上下文", "")
        yield _Section("Hook", "(无)")

    @staticmethod
    def _skills_summary() -> str:
        """诚实显示真实可用 skill 数(已接进活 loop:按 goal 召回进系统提示)。
        读盘失败 → 诚实退回'—',绝不谎报数量。"""
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
        self._set(6, f"↑{tokens_in} ↓{tokens_out}  {cost}\n"
                     f"缓存命中 {cache_read} tok  {elapsed_s:.1f}s")

    def on_context(self, *, used: int, window: int) -> None:
        """上下文窗口用量(当前窗口输入侧 token / 上限)。10 格进度条 + 百分比;
        口径对齐 Claude Code:used 是【当前窗口占用】(input+cache),非会话累计成本。"""
        pct = 0 if not window else round(used * 100 / window)
        filled = min(10, max(0, round(pct / 10)))
        bar = "▓" * filled + "░" * (10 - filled)
        win = f"{window // 1000}k" if window else "?"
        self._set(7, f"{self._model_label} · {win}\n{bar} {pct}%")

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
        self._set(8, "\n".join(lines) if lines else "(无)")

    def reset_run(self) -> None:
        self._phases.clear(); self._tool_counts.clear(); self._receipts.clear()
        self._todos.clear()
        self._hook_log.clear()
        self._set(1, "(待开始)"); self._set(2, "本轮 0 调用"); self._set(3, "—")
        self._set(8, "(无)")

    def snapshot_text(self) -> str:
        # Textual 8.2.7 的 Static 用 .content 暴露当前正文(随 .update() 刷新),不再有 .renderable。
        return "\n".join(str(s.content) + " " + str(s.border_title) for s in self._sections())
