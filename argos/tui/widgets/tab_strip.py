"""TUI TabStrip widget(v3 spec §4.x)——顶部 tab 条显示多 run 状态。

特性:
  · 每个 tab 显示状态字形 + goal[:24] + cost
  · 点击 tab → TabActivated(run_id) 消息
  · 键盘 Ctrl+1..5 / Ctrl+Tab / Ctrl+Shift+Tab
  · active tab 用底色块 $raise-2(不用 [reverse])
  · 顺序按 created_at 升序(老 tab 左,新 tab 右)

视觉规范(v3 spec §4.x, emoji 全处决):
  ◌ pending / ⏵ running / ⏸ paused / ⏹ suspended|cancelled /
  ◕ completed / ◉ failed

字形颜色规范(README §字形铁律):
  非活跃 failed tab 的 ◉ 字形必须染 $fail (#F7768E),其余非活跃字形保持
  widget 默认色 $ink-dim。活跃 tab 整段统一用 #ECEEF5 on #23263A。
"""
from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.message import Message
from textual.widgets import Static

try:
    from rich.cells import cell_len as _cell_len
except ImportError:  # pragma: no cover — Rich 版本极端回退
    def _cell_len(text: str) -> int:  # type: ignore[misc]
        return len(text)


# v3 spec §4.x: emoji 全处决，改用等宽安全字形(EAW=N)
_STATE_ICON = {
    "pending":   "◌",   # 空态/未睁
    "running":   "⏵",   # 运行控制:播放
    "paused":    "⏸",   # 运行控制:暂停
    "suspended": "⏹",   # 运行控制:停止
    "completed": "◕",   # 阅毕眼
    "failed":    "◉",   # 注视眼;非活跃时染 $fail (#F7768E),见 render()
    "cancelled": "⏹",   # 运行控制:停止
}

# Rich Text 层无法引用 CSS $token,用注释锚定对应 token
_COL_FAIL = "#F7768E"   # $fail: verdict failed / 唯一的红


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
    """按 cell 宽度截断(finding #33:CJK 字符占 2 cell,len() 会低估宽度)。

    n 是最大 cell 宽度。超出时从末尾逐字回退,保证输出 cell_len <= n-1 + 1(省略号)。
    """
    if _cell_len(text) <= n:
        return text
    # 逐字符回退,直到 cell_len(prefix) + 1(省略号) <= n
    result: list[str] = []
    used = 0
    for ch in text:
        ch_w = _cell_len(ch)
        if used + ch_w + 1 > n:  # +1 为省略号留位
            break
        result.append(ch)
        used += ch_w
    return "".join(result) + "…"


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
        """更新 tab 列表 + active 焦点。tabs 是按 spec §6.1 顺序的 list。

        tab dict: {run_id, goal, state, cost_usd}
        """
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
        """渲染 tab 条为 Rich markup 字符串。

        active tab 用底色块 $raise-2 + $ink-bright bold(v3 spec §4.x 裁决:不用 [reverse])。
        非活跃 failed tab 的 ◉ 字形单独染 $fail(README §字形铁律 line 90:error ◉ 失败)。
        hex 值与 theme.py 中对应 token 对齐:
          $raise-2 = #23263A, $ink-bright = #ECEEF5, $fail = #F7768E
        Rich Text 层无法引用 CSS $token 名,直接用 hex。
        """
        if not self._tabs:
            return "(no runs)"
        parts = []
        for t in self._tabs:
            icon = t["icon"]
            title = t["title"]
            cost = t["cost"]
            if t["run_id"] == self._active:
                # 活跃 tab: 整段 bold + $ink-bright 字 + $raise-2 底;不用 [reverse]
                seg = f"[bold #ECEEF5 on #23263A] {icon} {title} {cost} [/bold #ECEEF5 on #23263A]"
            elif t["state"] == "failed":
                # 非活跃 failed tab: ◉ 字形染 $fail,其余保持 widget 默认 $ink-dim
                seg = f"[{_COL_FAIL}]{icon}[/{_COL_FAIL}] {title} {cost}"
            else:
                seg = f"{icon} {title} {cost}"
            parts.append(seg)
        return "  ".join(parts)

    # ── 鼠标 + 键盘 ────────────────────────────────────────────────

    def on_click(self, event) -> None:
        """点击 tab → 找最近 run_id → 派消息。

        hit-test 用 cell 宽度而非 len()(finding #26:CJK tab 标题 click 偏移错误)。
        """
        x = event.x - 2   # padding 2(v3 spec §4.x)
        if x < 0 or not self._tabs:
            return
        # 算每个 tab 的 x 区间(按 cell_len 而非 str len)
        offset = 0
        for t in self._tabs:
            seg = f"{t['icon']} {t['title']} {t['cost']}"
            seg_width = _cell_len(seg)
            if offset <= x < offset + seg_width:
                self.post_message(TabActivated(t["run_id"]))
                return
            offset += seg_width + 2   # 2 空格分隔(两个 ASCII 空格 = 2 cells)

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
