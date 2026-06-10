"""StatusBar:always-on 状态条(TUI v2 spec §6.2)。

◇ plan · ⚙3 · ↑12.4k ↓3.1k · $0.013 · 4.2s · ctx 34%        Esc打断 · \\↵换行 · ^C退出
诚实:数字全来自 phase_change/cost_update 事件;无事件时显零态,不预填假数。
daemon run badges(⏵/⏸/⏹)只在 daemon 模式(set_run_summary 喂过数据)渲染——
非 daemon 不再显示 ⏵0/⏸0/⏹0 噪声。键提示右对齐(替代 stock Footer)。
"""
from __future__ import annotations

from rich.text import Text
from textual.reactive import reactive
from textual.widgets import Static

from argos_agent.core.types import Phase

_PHASE_GLYPH = {"plan": "◇", "act": "✦", "verify": "✦", "report": "◇", "idle": "·"}
# 与 glow.phase_color 同源的固定色(Rich style 无法引用 Textual CSS 变量)
_PHASE_STYLE = {
    "plan": "#7AA2F7", "act": "#E0AF68", "verify": "#73DACA", "report": "#A9B1D6",
}
_MUTED = "#565F89"
_ERROR = "#F7768E"
_HINTS = "Esc 打断 · \\↵ 换行 · ^C 退出"


def _k(n: int) -> str:
    """token 千分缩写:12400 → 12.4k;<1000 原样。"""
    if n >= 1000:
        return f"{n / 1000:.1f}k"
    return str(n)


class StatusBar(Static):
    DEFAULT_CSS = """
    StatusBar { dock: bottom; height: 1; background: $panel; color: $text-muted; padding: 0 1; }
    StatusBar.-plan-mode { color: $primary; }
    StatusBar.-ctx-warn { color: $error; text-style: bold; }
    """

    phase: reactive[str] = reactive("idle")
    actions: reactive[int] = reactive(0)
    tokens_in: reactive[int] = reactive(0)
    tokens_out: reactive[int] = reactive(0)
    cost_usd: reactive[float | None] = reactive(0.0)
    elapsed_s: reactive[float] = reactive(0.0)
    plan_mode: reactive[bool] = reactive(False)
    # #12 上下文压力(0-1,>0.8 红色加粗;0 = 未知 / 关掉)
    ctx_pct: reactive[float] = reactive(0.0)

    def __init__(self, **kwargs) -> None:
        # render() 自绘(Rich Text 分段着色 + 右对齐键提示),不走 markup 解析(防崩)。
        super().__init__("", markup=False, **kwargs)

    @property
    def render_text(self) -> str:
        """左侧数据段纯文本(/status 回显与测试断言的单一真源)。"""
        cost = "$(N/A)" if self.cost_usd is None else f"${self.cost_usd:.3f}"
        glyph = _PHASE_GLYPH.get(self.phase, "·")
        parts = [
            f"{glyph} {self.phase}",
            f"⚙{self.actions}",
            f"↑{_k(self.tokens_in)} ↓{_k(self.tokens_out)}",
            cost,
            f"{self.elapsed_s:.1f}s",
        ]
        if self.ctx_pct > 0:
            parts.append(f"ctx {round(self.ctx_pct * 100)}%")
        if self.plan_mode:
            parts.append("[plan mode]")
        badges = self.render_count_badges(self._run_summary)
        if badges:
            parts.append(badges)
        return " · ".join(parts)

    # ── Run 计数 badges(daemon 模式才渲染)────────────────────────────
    _run_summary: list[tuple[str, str]] = []

    def set_run_summary(self, runs: list[tuple[str, str]]) -> None:
        """runs: [(run_id, state), ...];空列表 = 非 daemon,徽标整段消失(去噪)。"""
        self._run_summary = list(runs)
        self._refresh()

    def render_count_badges(self, runs: list[tuple[str, str]]) -> str:
        """run 列表 → 紧凑 count badges:`⏵1 / ⏸0 / ⏹3`;无 run(非 daemon)→ 空串。

        active = running;paused = paused;history = suspended+completed+failed+cancelled。"""
        if not runs:
            return ""
        active = sum(1 for _, s in runs if s == "running")
        paused = sum(1 for _, s in runs if s == "paused")
        history = sum(1 for _, s in runs
                      if s in ("suspended", "completed", "failed", "cancelled"))
        return f"⏵{active} / ⏸{paused} / ⏹{history}"

    def set_phase(self, phase: Phase, actions: int) -> None:
        self.phase = phase
        self.actions = actions

    def set_cost(self, *, tokens_in: int, tokens_out: int, cost_usd: float | None, elapsed_s: float) -> None:
        self.tokens_in = tokens_in
        self.tokens_out = tokens_out
        self.cost_usd = cost_usd
        self.elapsed_s = elapsed_s

    def set_plan_mode(self, active: bool) -> None:
        """host 切 plan mode 时调:加 [plan mode] 段 + 切色。"""
        self.plan_mode = bool(active)

    def update_ctx_pressure(self, pct: float) -> None:
        """#12 Context 可视化:>80% 时整条切 .ctx-warn 红色加粗;pct=0(无数据)→ 移除。"""
        self.ctx_pct = max(0.0, min(1.0, float(pct or 0.0)))

    def render(self) -> Text:
        left = Text(self.render_text)
        glyph = _PHASE_GLYPH.get(self.phase, "·")
        style = _PHASE_STYLE.get(self.phase)
        if style and left.plain.startswith(glyph):
            left.stylize(style, 0, len(glyph))
        if self.ctx_pct >= 0.8:
            # 红点保留在 ctx 段尾部之外的视觉强化由 .ctx-warn class 承担
            pass
        width = self.size.width or 0
        hints = Text(_HINTS, style=_MUTED)
        pad = width - left.cell_len - hints.cell_len - 2
        if pad >= 1:
            return Text.assemble(left, " " * pad, hints)
        return left

    def _refresh(self) -> None:
        self.refresh()
        self.set_class(self.plan_mode, "-plan-mode")
        self.set_class(self.ctx_pct >= 0.8, "-ctx-warn")

    # 每个 reactive 字段一个独立 watch_ 方法(不用别名赌注)。
    def watch_phase(self, value: str) -> None:
        self._refresh()

    def watch_actions(self, value: int) -> None:
        self._refresh()

    def watch_tokens_in(self, value: int) -> None:
        self._refresh()

    def watch_tokens_out(self, value: int) -> None:
        self._refresh()

    def watch_cost_usd(self, value: float | None) -> None:
        self._refresh()

    def watch_elapsed_s(self, value: float) -> None:
        self._refresh()

    def watch_plan_mode(self, value: bool) -> None:  # noqa: ARG002
        self._refresh()

    def watch_ctx_pct(self, value: float) -> None:  # noqa: ARG002
        self._refresh()
