"""右侧诚实活动栏(spec §ActivityPanel)。区块:模型/任务进度/工具/回执/Skills/MCP/成本+缓存。
诚实铁律:每块只反映真实数据;Skills/MCP 无真实内容时显示诚实空态('未加载'/'0 已连接')。"""
from __future__ import annotations

import time

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.widgets import Static

_PHASE_GLYPH = {"plan": "◇", "act": "✦", "verify": "✦", "report": "◇"}


class _Section(Static):
    DEFAULT_CSS = """
    _Section { height: auto; padding: 0 1; }
    """
    def __init__(self, title: str, body: str = "") -> None:
        super().__init__(body)
        self.border_title = title


class ActivityPanel(Vertical):
    DEFAULT_CSS = """
    ActivityPanel { width: 34; border-left: solid $panel; padding: 0 0; }
    ActivityPanel > _Section { border-top: solid $panel; }
    """
    def __init__(self, *, model_label: str = "—", tier: str = "—", **kwargs) -> None:
        super().__init__(**kwargs)
        self._model_label = model_label
        self._tier = tier
        self._phases: list[tuple[str, float, str]] = []   # (phase, elapsed, status)
        self._phase_start = 0.0
        self._tool_counts: dict[str, int] = {}
        self._receipts: list[str] = []

    def compose(self) -> ComposeResult:
        yield _Section("模型", self._model_label)
        yield _Section("任务进度", "(待开始)", )  # id 设下方
        yield _Section("工具", "本轮 0 调用")
        yield _Section("回执(已签名)", "—")
        yield _Section("Skills", "未加载")
        yield _Section("MCP", "0 已连接")
        yield _Section("成本 + 缓存", "↑0 ↓0  $0.000\n缓存命中 0 tok  0.0s")
        yield _Section("上下文", "")

    def _sections(self) -> list[_Section]:
        return list(self.query(_Section))

    def _set(self, idx: int, body: str) -> None:
        self._sections()[idx].update(body)

    # ── 事件入口(app._apply_event 调) ──────────────────────────────
    def on_phase(self, phase: str, actions: int) -> None:
        now = time.time()
        if self._phases:
            p, _, _ = self._phases[-1]
            self._phases[-1] = (p, max(0.0, now - self._phase_start), "✓")
        self._phase_start = now
        self._phases.append((phase, 0.0, "▶"))
        lines = []
        for p, e, s in self._phases:
            # 进行中(▶,elapsed 还是 0.0)显 …;完成且无耗时显 —;否则显真实耗时。
            elapsed = "…" if s == "▶" else (f"{e:.1f}s" if e else "—")
            lines.append(f" {_PHASE_GLYPH.get(p, '◇')} {p:<7} {elapsed:>5} {s}")
        self._set(1, "\n".join(lines))

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

    def reset_run(self) -> None:
        self._phases.clear(); self._tool_counts.clear(); self._receipts.clear()
        self._set(1, "(待开始)"); self._set(2, "本轮 0 调用"); self._set(3, "—")

    def snapshot_text(self) -> str:
        # Textual 8.2.7 的 Static 用 .content 暴露当前正文(随 .update() 刷新),不再有 .renderable。
        return "\n".join(str(s.content) + " " + str(s.border_title) for s in self._sections())
