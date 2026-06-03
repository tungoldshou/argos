"""CostMeter:侧栏成本明细(spec §4.1 右侧停靠栏)。

每次 cost_update 用累计值刷新(loop 投的是累计量,直接覆盖)。
"""
from __future__ import annotations

from textual.reactive import reactive
from textual.widgets import Static


class CostMeter(Static):
    tokens_in: reactive[int] = reactive(0)
    tokens_out: reactive[int] = reactive(0)
    cost_usd: reactive[float] = reactive(0.0)
    elapsed_s: reactive[float] = reactive(0.0)

    def __init__(self, **kwargs) -> None:
        super().__init__("", **kwargs)

    @property
    def render_text(self) -> str:
        return (
            "成本明细\n"
            f"  输入 token : {self.tokens_in}\n"
            f"  输出 token : {self.tokens_out}\n"
            f"  累计成本   : ${self.cost_usd:.3f}\n"
            f"  墙钟       : {self.elapsed_s:.1f}s"
        )

    def update_cost(self, *, tokens_in: int, tokens_out: int, cost_usd: float, elapsed_s: float) -> None:
        self.tokens_in = tokens_in
        self.tokens_out = tokens_out
        self.cost_usd = cost_usd
        self.elapsed_s = elapsed_s

    def _refresh(self) -> None:
        self.update(self.render_text)

    def watch_tokens_in(self, value: int) -> None:
        self._refresh()

    def watch_tokens_out(self, value: int) -> None:
        self._refresh()

    def watch_cost_usd(self, value: float) -> None:
        self._refresh()

    def watch_elapsed_s(self, value: float) -> None:
        self._refresh()
