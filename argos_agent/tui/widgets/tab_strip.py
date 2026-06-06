"""TUI TabStrip widget(#5b §6)——顶部 tab 条显示多 run 状态。

特性:
  · 每个 tab 显示图标 + goal[:24] + cost
  · 点击 tab → TabActivated(run_id) 消息
  · 键盘 Ctrl+1..5 / Ctrl+Tab / Ctrl+Shift+Tab
  · active tab 用 $accent 暖橙背景
  · 顺序按 created_at 升序(老 tab 左,新 tab 右)

视觉规范(spec §6.1):
  🟢 running / 🟡 paused / ⚪ suspended / 🔴 failed / ❌ cancelled / ✓ completed / ⏳ pending
"""
from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.message import Message
from textual.widgets import Static


_STATE_ICON = {
    "pending": "⏳",
    "running": "🟢",
    "paused": "🟡",
    "suspended": "⚪",
    "completed": "✓",
    "failed": "🔴",
    "cancelled": "❌",
}


def _format_cost(usd: float | None) -> str:
    """spec §6.2 cost 简写:精度 2 位小数,> $1 显示整数位,< $0.01 显示 $<0.01。"""
    if usd is None:
        return "$N/A"
    if usd < 0.01:
        return "$<0.01"
    if usd >= 1.0:
        return f"${usd:.2f}"
    return f"${usd:.3f}"


def _truncate(text: str, n: int) -> str:
    if len(text) <= n:
        return text
    return text[: n - 1] + "…"


class TabActivated(Message):
    """用户激活某 tab 时发(spec §6.3)。"""

    def __init__(self, run_id: str) -> None:
        super().__init__()
        self.run_id = run_id


class TabStrip(Static):
    """顶部 tab 条;高度 1 行。"""

    DEFAULT_CSS = """
    TabStrip {
        height: 1;
        background: $surface;
        color: $text-muted;
        padding: 0 1;
    }
    TabStrip .tab-active {
        background: $accent;
        color: $background;
        text-style: bold;
    }
    """

    BINDINGS = [
        ("ctrl+1", "select_tab(0)"),
        ("ctrl+2", "select_tab(1)"),
        ("ctrl+3", "select_tab(2)"),
        ("ctrl+4", "select_tab(3)"),
        ("ctrl+5", "select_tab(4)"),
        ("ctrl+tab", "next_tab"),
        ("ctrl+shift+tab", "prev_tab"),
    ]

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._tabs: list[dict] = []   # [{run_id, title, icon, cost, state}]
        self._active: str | None = None

    # ── public API ──────────────────────────────────────────────────

    def update_tabs(self, tabs: list[dict], *, active: str | None = None) -> None:
        """更新 tab 列表 + active 焦点。tabs 是按 spec §6.1 顺序的 list。

        tab dict: {run_id, goal, state, cost_usd}
        """
        rendered = []
        for t in tabs:
            rendered.append({
                "run_id": t["run_id"],
                "title": _truncate(t.get("goal", ""), 24),
                "icon": _STATE_ICON.get(t.get("state", "pending"), "⏳"),
                "cost": _format_cost(t.get("cost_usd")),
                "state": t.get("state", "pending"),
            })
        self._tabs = rendered
        if active is not None:
            self._active = active
        self.refresh()

    def set_active(self, run_id: str) -> None:
        self._active = run_id
        self.refresh()

    def render(self) -> str:
        if not self._tabs:
            return "(no runs)"
        parts = []
        for t in self._tabs:
            seg = f"{t['icon']} {t['title']} {t['cost']}"
            if t["run_id"] == self._active:
                seg = f"[reverse] {seg} [/reverse]"
            parts.append(seg)
        return "  ".join(parts)

    # ── 鼠标 + 键盘 ────────────────────────────────────────────────

    def on_click(self, event) -> None:
        """点击 tab → 找最近 run_id → 派消息。"""
        x = event.x - 1   # padding 1
        if x < 0 or not self._tabs:
            return
        # 算每个 tab 的 x 区间
        offset = 0
        for t in self._tabs:
            seg = f"{t['icon']} {t['title']} {t['cost']}"
            seg_len = len(seg)
            if offset <= x < offset + seg_len:
                self.post_message(TabActivated(t["run_id"]))
                return
            offset += seg_len + 2   # 2 空格分隔

    def action_select_tab(self, idx: int) -> None:
        if 0 <= idx < len(self._tabs):
            self.post_message(TabActivated(self._tabs[idx]["run_id"]))

    def action_next_tab(self) -> None:
        if not self._tabs:
            return
        # 找当前 active 的索引
        current = -1
        for i, t in enumerate(self._tabs):
            if t["run_id"] == self._active:
                current = i
                break
        next_idx = (current + 1) % len(self._tabs)
        self.post_message(TabActivated(self._tabs[next_idx]["run_id"]))

    def action_prev_tab(self) -> None:
        if not self._tabs:
            return
        current = -1
        for i, t in enumerate(self._tabs):
            if t["run_id"] == self._active:
                current = i
                break
        prev_idx = (current - 1) % len(self._tabs)
        self.post_message(TabActivated(self._tabs[prev_idx]["run_id"]))

    def get_active(self) -> str | None:
        return self._active

    def get_tabs(self) -> list[dict]:
        return list(self._tabs)
