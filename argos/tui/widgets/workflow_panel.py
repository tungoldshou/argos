"""WorkflowPanel:Dynamic Workflows 实时进度树(Task 12)。

挂进 transcript:标题行「工作流:<name>」+ 每个子 agent 一行「<agent_id> <phase>」。
update_progress(agent_id, phase, note) 刷新单 agent 阶段;finish(synthesis, notes) 标完成。

诚实铁律:
  · error phase 如实显「失败」、done 显「完成」,绝不把失败渲染成完成。
  · markup=False:agent_id / phase / note 可能含 `[...]`(trace、用例名、列表),
    不可被当 Rich markup 解析 —— 否则崩整个 TUI(全 TUI 铁律,见 test_tui_markup_safety)。

颜色铁律(design-audit fix 2026-06-14):
  · 字形着色用 Rich Text.append(glyph, style=hex),绝不用 markup=[color]...
  · 所有 hex 常量单源于此模块顶部,与 theme.py token 一一对应;勿在其他地方硬编码。
"""
from __future__ import annotations

from rich.text import Text
from textual.widgets import Static

from argos.i18n import t

# ── 颜色常量(单源,对应 argos/tui/theme.py token)────────────────────────────
# $ink-bright (#ECEEF5) — bold 标题
_COL_INK_BRIGHT = "#ECEEF5"
# $eye (#D9A85C)        — 进行中字形(plan/act/verify)
_COL_EYE = "#D9A85C"
# $pass (#9ECE6A)       — 完成/汇总字形(done/report)
_COL_PASS = "#9ECE6A"
# $fail (#F7768E)       — 失败字形(error)
_COL_FAIL = "#F7768E"
# $ink-dim (#7E869C)    — 综合结论行(次要元信息)
_COL_INK_DIM = "#7E869C"
# $ink-faint (#525A73)  — 诚实注记行(最低层级)
_COL_INK_FAINT = "#525A73"

# phase → 简明标签。error/done 标记分明(诚实:告警与完成不可混淆)。
# _PHASE_KEY:  i18n key map (single source of truth for render and tests).
# _PHASE_TEXT: derived at import time via t() — imported by tests for contract assertions.
#              Values reflect the active ARGOS_LANG (ZH in test suite, EN by default).
_PHASE_KEY = {
    "plan":   "widget.phase_plan",
    "act":    "widget.phase_act",
    "verify": "widget.phase_verify",
    "report": "widget.phase_report",
    "done":   "widget.phase_done",
    "error":  "widget.phase_error",
}
_PHASE_TEXT = {phase: t(key) for phase, key in _PHASE_KEY.items()}
_PHASE_GLYPH = {
    "plan": "◔",
    "act": "◉",
    "verify": "❂",
    "report": "◕",
    "done": "◕",
    "error": "◉",
}
# phase → 字形颜色(诚实区隔:in-progress=金/$eye, done/report=绿/$pass, error=红/$fail)
_PHASE_GLYPH_COLOR = {
    "plan":   _COL_EYE,
    "act":    _COL_EYE,
    "verify": _COL_EYE,
    "report": _COL_PASS,
    "done":   _COL_PASS,
    "error":  _COL_FAIL,
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
        """当前面板纯文本(供测试断言;从 Rich Text 提取去色纯文本)。"""
        return self._compose_text().plain

    def _compose_text(self) -> Text:
        """组装进度树 Rich Text(per-glyph 着色)。

        返回 rich.text.Text 而非 str,使每个字形可独立着色,同时保持
        markup=False 约束 —— agent_id/phase/note 以 Text.append(plain) 方式
        追加,绝不经过 markup 解析(防崩 TUI 铁律)。
        注:方法名避开 Textual Widget._render(覆盖它会让渲染返回 None 崩)。
        """
        result = Text(no_wrap=False, end="")

        # [LOW fix] 标题行:bold + $ink-bright (#ECEEF5)
        if self._done:
            head = t("widget.workflow_title_done", name=self._name)
        else:
            head = t("widget.workflow_title", name=self._name)
        result.append(head, style=f"bold {_COL_INK_BRIGHT}")

        for agent_id in self._order:
            phase, note = self._agents[agent_id]
            glyph = _PHASE_GLYPH.get(phase, "·")
            phase_text = t(_PHASE_KEY.get(phase, "widget.phase_plan")) if phase in _PHASE_KEY else phase
            glyph_color = _PHASE_GLYPH_COLOR.get(phase, _COL_EYE)

            result.append("\n  ")
            # [MEDIUM fix] 字形单独着色,余下纯文本追加(防 markup 解析崩溃)
            result.append(glyph, style=glyph_color)
            result.append(f" {agent_id} {phase_text}")
            if note:
                result.append(f" — {note}")

        if self._done:
            # [LOW fix] 综合结论行:$ink-dim (#7E869C)
            result.append(t("widget.workflow_synthesis_label"), style=_COL_INK_DIM)
            result.append(self._synthesis, style=_COL_INK_DIM)
            # [LOW fix] 诚实注记行:$ink-faint (#525A73)
            for n in self._notes:
                result.append("\n    · ", style=_COL_INK_FAINT)
                result.append(n, style=_COL_INK_FAINT)

        return result
