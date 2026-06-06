"""StatusBar:always-on 状态条(spec §4.1/§4.6 差异化核心)。

⏵ phase:verify · ⚙3 actions · ↑12.4k↓3.1k tok · 💰$0.013 · ⏱4.2s · Mode:act
诚实:数字全来自 phase_change/cost_update 事件;无事件时显零态,不预填假数。
Mode 段在 plan mode 期间显 [plan mode] 前缀 + 改色(spec §2.4)。
"""
from __future__ import annotations

from textual.reactive import reactive
from textual.widgets import Static

from argos_agent.core.types import Phase


def _k(n: int) -> str:
    """token 千分缩写:12400 → 12.4k;<1000 原样。"""
    if n >= 1000:
        return f"{n / 1000:.1f}k"
    return str(n)


class StatusBar(Static):
    # dock 底部、$panel 填充贯穿、整条 $text-muted 朴素文本(点分隔;成本明细在右侧活动栏)。
    # Mode 段在 plan mode 期间切到 $primary(冷靛蓝),其他时段 $text-muted。
    # #12 Context 可视化:>80% 时加 .ctx-warn 红点(最小装饰,无文字)。
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
    # #12 上下文压力(0-1,>0.8 红点;0 = 未知 / 关掉)
    ctx_pct: reactive[float] = reactive(0.0)

    def __init__(self, **kwargs) -> None:
        # markup=False:状态栏含模型名等动态串,统一关 markup 解析(防任意文本里的 `[...]` 崩)。
        super().__init__("", markup=False, **kwargs)

    @property
    def render_text(self) -> str:
        cost = "$(N/A)" if self.cost_usd is None else f"${self.cost_usd:.3f}"
        mode_str = "plan" if self.plan_mode else "act"
        # run 计数 badges(daemon 模式,默认 0/0/0)
        run_badges = self.render_count_badges(self._run_summary)
        return (
            f"⏵ phase:{self.phase} · ⚙{self.actions} actions · "
            f"↑{_k(self.tokens_in)}↓{_k(self.tokens_out)} tok · "
            f"💰{cost} · ⏱{self.elapsed_s:.1f}s · Mode:{mode_str}  {run_badges}"
        )

    # ── Run 计数 badges(spec §2.5 d 段)────────────────────────────
    # ⏵N active / ⏸N paused / ⏹N history
    # 由 app.on_run_state_changed 推(daemon 模式;legacy 模式给空元组)
    _run_summary: list[tuple[str, str]] = []

    def set_run_summary(self, runs: list[tuple[str, str]]) -> None:
        """runs: [(run_id, state), ...]"""
        self._run_summary = list(runs)
        self._refresh()

    def render_count_badges(self, runs: list[tuple[str, str]]) -> str:
        """run 列表 → 紧凑 count badges:`⏵1 / ⏸0 / ⏹3`。

        active = running;paused = paused;history = suspended+completed+failed+cancelled。
        单 TUI 模式:始终显示 0/0/0 表示"无 daemon"(诚实)。"""
        if not runs:
            return "⏵0 / ⏸0 / ⏹0"
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
        """host 切 plan mode 时调:改文案 Mode 段 + 切色。"""
        self.plan_mode = bool(active)

    def update_ctx_pressure(self, pct: float) -> None:
        """#12 Context 可视化(spec §10.4 + D8):>80% 加 .ctx-warn class;不显文字,只切色。
        pct=0(无数据)→ 移除。"""
        self.ctx_pct = max(0.0, min(1.0, float(pct or 0.0)))

    def _refresh(self) -> None:
        self.update(self.render_text)
        self.set_class(self.plan_mode, "-plan-mode")
        # ctx_warn 在 render_text 末位追加点(spec §10.4 最小装饰)
        if self.ctx_pct >= 0.8:
            self.update(self.render_text + "  ●")
        self.set_class(self.ctx_pct >= 0.8, "-ctx-warn")

    # P2-2:每个 reactive 字段一个独立 watch_ 方法(不用别名赌注)。
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
