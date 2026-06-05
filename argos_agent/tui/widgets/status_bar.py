"""StatusBar:always-on 状态条(spec §4.1/§4.6 差异化核心)。

⏵ phase:verify · ⚙3 actions · ↑12.4k↓3.1k tok · 💰$0.013 · ⏱4.2s
诚实:数字全来自 phase_change/cost_update 事件;无事件时显零态,不预填假数。
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
    DEFAULT_CSS = """
    StatusBar { dock: bottom; height: 1; background: $panel; color: $text-muted; padding: 0 1; }
    """

    phase: reactive[str] = reactive("idle")
    actions: reactive[int] = reactive(0)
    tokens_in: reactive[int] = reactive(0)
    tokens_out: reactive[int] = reactive(0)
    cost_usd: reactive[float | None] = reactive(0.0)
    elapsed_s: reactive[float] = reactive(0.0)

    def __init__(self, **kwargs) -> None:
        # markup=False:状态栏含模型名等动态串,统一关 markup 解析(防任意文本里的 `[...]` 崩)。
        super().__init__("", markup=False, **kwargs)

    @property
    def render_text(self) -> str:
        cost = "$(N/A)" if self.cost_usd is None else f"${self.cost_usd:.3f}"
        return (
            f"⏵ phase:{self.phase} · ⚙{self.actions} actions · "
            f"↑{_k(self.tokens_in)}↓{_k(self.tokens_out)} tok · "
            f"💰{cost} · ⏱{self.elapsed_s:.1f}s"
        )

    def set_phase(self, phase: Phase, actions: int) -> None:
        self.phase = phase
        self.actions = actions

    def set_cost(self, *, tokens_in: int, tokens_out: int, cost_usd: float | None, elapsed_s: float) -> None:
        self.tokens_in = tokens_in
        self.tokens_out = tokens_out
        self.cost_usd = cost_usd
        self.elapsed_s = elapsed_s

    def _refresh(self) -> None:
        self.update(self.render_text)

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
