# argos_agent/tui/widgets/top_bar.py
"""TopBar:自绘单行顶栏(TUI v2 spec §1.1),替代 stock Header + sub_title 机制。

左:✳ Argos v{version} · {model};右:状态徽标(plan mode / YOLO / DEMO / 未配 key)。
徽标全部来自真实状态(诚实铁律:DEMO 标识绝不可省;真 loop 注入 demo=False 后自动消失;
LIVE 但无 key 时显 ⚠ 未配 key,绝不撒 LIVE 的谎)。
用 render() 返回 Rich Text 做左右对齐与分段着色 —— 不走 markup 解析(防任意文本崩)。
"""
from __future__ import annotations

from rich.text import Text
from textual.widgets import Static

# 与 theme.ARGOS_NIGHT 同源的固定色(Rich style 无法引用 Textual CSS 变量)
_ACCENT = "#E0AF68"
_FG = "#C0CAF5"
_MUTED = "#565F89"
_PLAN = "#7AA2F7"      # 冷靛蓝(对齐 glow.phase_color("plan"))
_WARN = "#E0AF68"


class TopBar(Static):
    DEFAULT_CSS = """
    TopBar { height: 1; background: $surface; padding: 0 1; }
    """

    def __init__(self, *, version: str = "0.x", model_label: str = "—", **kwargs) -> None:
        super().__init__("", **kwargs)
        self._version = version
        self._model = model_label
        self._plan_mode = False
        self._yolo = False
        self._demo = True
        self._has_key = True

    def set_state(
        self, *,
        model_label: str | None = None,
        plan_mode: bool | None = None,
        yolo: bool | None = None,
        demo: bool | None = None,
        has_key: bool | None = None,
    ) -> None:
        """app 侧状态变化的单入口(任意子集更新);只重渲,不解析。"""
        if model_label is not None:
            self._model = model_label
        if plan_mode is not None:
            self._plan_mode = bool(plan_mode)
        if yolo is not None:
            self._yolo = bool(yolo)
        if demo is not None:
            self._demo = bool(demo)
        if has_key is not None:
            self._has_key = bool(has_key)
        self.refresh()

    def badges(self) -> list[str]:
        """当前应显示的徽标文本列表(渲染与测试断言共用的单一真源)。"""
        out: list[str] = []
        if self._plan_mode:
            out.append("[plan mode]")
        if self._yolo:
            out.append("⏻ YOLO")
        if self._demo:
            out.append("DEMO 脚本演示")
        elif not self._has_key:
            out.append("⚠ 未配 key")
        return out

    @property
    def render_text(self) -> str:
        """纯文本快照(测试断言用)。"""
        return str(self.render())

    def render(self) -> Text:
        left = Text()
        left.append("✳ ", style=f"bold {_ACCENT}")
        left.append(f"Argos v{self._version}", style=f"bold {_FG}")
        left.append(f" · {self._model}", style=_MUTED)
        right = Text()
        styles = {"[plan mode]": _PLAN, "⏻ YOLO": _ACCENT}
        for i, b in enumerate(self.badges()):
            if i:
                right.append("  ")
            right.append(b, style=styles.get(b, _WARN))
        width = self.size.width or 0
        pad = max(1, width - left.cell_len - right.cell_len - 2)
        return Text.assemble(left, " " * pad, right) if right.cell_len else left
