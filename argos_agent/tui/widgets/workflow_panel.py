"""WorkflowPanel:Dynamic Workflows 实时进度树(Task 12)。

挂进 transcript:标题行「⚙ 工作流:<name>」+ 每个子 agent 一行「<agent_id> <phase>」。
update_progress(agent_id, phase, note) 刷新单 agent 阶段;finish(synthesis, notes) 标完成。

诚实铁律:
  · error phase 如实显「失败」、done 显「完成」,绝不把失败渲染成完成。
  · markup=False:agent_id / phase / note 可能含 `[...]`(trace、用例名、列表),
    不可被当 Rich markup 解析 —— 否则崩整个 TUI(全 TUI 铁律,见 test_tui_markup_safety)。
"""
from __future__ import annotations

from textual.widgets import Static

# phase → 简明中文 + 标记。error/done 标记分明(诚实:告警与完成不可混淆)。
_PHASE_TEXT = {
    "plan": "规划",
    "act": "执行",
    "verify": "验证",
    "report": "汇总",
    "done": "完成",
    "error": "失败",
}
_PHASE_GLYPH = {
    "plan": "◇",
    "act": "▶",
    "verify": "✦",
    "report": "◇",
    "done": "✓",
    "error": "✗",
}


class WorkflowPanel(Static):
    """一个工作流的进度树。逐 agent 维护当前 phase,整体渲染成多行文本。"""

    DEFAULT_CSS = """
    WorkflowPanel {
        border: round $accent;
        padding: 0 1;
        margin: 0 1 1 1;
        height: auto;
    }
    """

    def __init__(self, *, name: str, **kwargs) -> None:
        # markup=False:进度树正文含 agent_id/phase/note 任意文本(可能带 `[...]`),
        # 按纯文本渲染防崩(全 TUI 铁律)。update() 沿用此 markup 设置。
        super().__init__("", markup=False, **kwargs)
        self._name = name
        # 顺序敏感:用 list 记录 agent 首次出现顺序,dict 存当前 (phase, note)。
        self._order: list[str] = []
        self._agents: dict[str, tuple[str, str]] = {}
        self._done = False
        self._synthesis = ""
        self._notes: tuple[str, ...] = ()
        # 初始正文直接给构造器(空 update 在未挂载时会让 _render() 返回 None → get_height 崩);
        # 后续 update_progress/finish 再走 self.update() 刷新。
        self.update(self._compose_text())

    def update_progress(self, agent_id: str, phase: str, note: str = "") -> None:
        """某子 agent 阶段流转 → 刷新它那一行。新 agent 追加到树尾。"""
        if agent_id not in self._agents:
            self._order.append(agent_id)
        self._agents[agent_id] = (phase, note)
        self.update(self._compose_text())

    def finish(self, synthesis: str, notes: tuple[str, ...] = ()) -> None:
        """工作流引擎跑完 → 标完成,把综合结论 + 诚实注记并入面板底部。"""
        self._done = True
        self._synthesis = synthesis
        self._notes = tuple(notes or ())
        self.update(self._compose_text())

    @property
    def rendered_text(self) -> str:
        """当前面板纯文本(供测试断言;Static.content 随 update 刷新)。"""
        return str(self.content)

    def _compose_text(self) -> str:
        """组装进度树纯文本。注:方法名避开 Textual Widget._render(覆盖它会让渲染返回 None 崩)。"""
        head = "⚙ 工作流:" + self._name
        if self._done:
            head += "(完成)"
        lines = [head]
        for agent_id in self._order:
            phase, note = self._agents[agent_id]
            glyph = _PHASE_GLYPH.get(phase, "·")
            text = _PHASE_TEXT.get(phase, phase)
            row = f"  {glyph} {agent_id} {text}"
            if note:
                row += f" — {note}"
            lines.append(row)
        if self._done:
            lines.append("  ─ 综合结论:" + self._synthesis)
            for n in self._notes:
                lines.append("    · " + n)
        return "\n".join(lines)
