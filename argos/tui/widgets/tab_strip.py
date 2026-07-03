from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.message import Message
from textual.widgets import Static

try:
    from rich.cells import cell_len as _cell_len
except ImportError:  # pragma: no cover
    def _cell_len(text: str) -> int:  # type: ignore[misc]
        return len(text)


_STATE_ICON = {
    "pending":   "◌",
    "running":   "⏵",
    "paused":    "⏸",
    "suspended": "⏹",
    "completed": "◕",
    "failed":    "◉",
    "cancelled": "⏹",
}

_COL_FAIL = "#F7768E"


def _format_cost(usd: float | None) -> str:
    if usd is None:
        return "$N/A"
    if usd < 0.01:
        return "$<0.01"
    if usd >= 1.0:
        return f"${usd:.2f}"
    return f"${usd:.3f}"


def _truncate(text: str, n: int) -> str:
    if _cell_len(text) <= n:
        return text
    result: list[str] = []
    used = 0
    for ch in text:
        ch_w = _cell_len(ch)
        if used + ch_w + 1 > n:
            break
        result.append(ch)
        used += ch_w
    return "".join(result) + "…"


class TabActivated(Message):

    def __init__(self, run_id: str) -> None:
        super().__init__()
        self.run_id = run_id


class TabStrip(Static):

    DEFAULT_CSS = """
    TabStrip {
        height: 1;
        background: $well;
        color: $ink-dim;
        padding: 0 2;
        border-bottom: solid $hairline;
    }
    TabStrip .tab-active {
        background: $raise-2;
        color: $ink-bright;
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
        rendered = []
        for t in tabs:
            rendered.append({
                "run_id": t["run_id"],
                "title": _truncate(t.get("goal", ""), 24),
                "icon": _STATE_ICON.get(t.get("state", "pending"), "◌"),
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
            icon = t["icon"]
            title = t["title"]
            cost = t["cost"]
            if t["run_id"] == self._active:
                seg = f"[bold #ECEEF5 on #23263A] {icon} {title} {cost} [/bold #ECEEF5 on #23263A]"
            elif t["state"] == "failed":
                seg = f"[{_COL_FAIL}]{icon}[/{_COL_FAIL}] {title} {cost}"
            else:
                seg = f"{icon} {title} {cost}"
            parts.append(seg)
        return "  ".join(parts)


    def on_click(self, event) -> None:
        x = event.x - 2   # padding 2(v3 spec §4.x)
        if x < 0 or not self._tabs:
            return
        offset = 0
        for t in self._tabs:
            seg = f"{t['icon']} {t['title']} {t['cost']}"
            seg_width = _cell_len(seg)
            if offset <= x < offset + seg_width:
                self.post_message(TabActivated(t["run_id"]))
                return
            offset += seg_width + 2

    def action_select_tab(self, idx: int) -> None:
        if 0 <= idx < len(self._tabs):
            self.post_message(TabActivated(self._tabs[idx]["run_id"]))

    def action_next_tab(self) -> None:
        if not self._tabs:
            return
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
