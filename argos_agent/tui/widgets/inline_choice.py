# argos_agent/tui/widgets/inline_choice.py
"""InlineChoice:流内选择组件(TUI v2 spec §4)——替代居中 ModalScreen 的统一审批/决策交互。

挂进 Transcript 流内(mount_block),三个场景复用:
  · 工具审批(once/session/always/deny)
  · 计划决策(approve_start/approve_accept_edits/keep_planning/refine——refine 就地展开反馈输入)
  · 工作流审批(once/always/deny)

交互:mount 时夺焦 + 终端铃(app.bell,用户要求的提示音);↑/↓ 移 ▸ 光标;Enter 确认;
数字 1-9 直选;Esc = escape_value(无则忽略,fail-closed 场景由调用方传 "deny")。
决策后调 on_decide(value, feedback) 并自毁;焦点还给 #prompt(输入草稿不丢)。
markup=False / Rich Text 渲染:正文常含 `[...]`(命令参数/preview),绝不当 markup 解析。
"""
from __future__ import annotations

from collections.abc import Callable

from rich.text import Text
from textual import events
from textual.app import ComposeResult
from textual.containers import Vertical
from textual.widgets import Input, Static

_ACCENT = "#E0AF68"
_MUTED = "#565F89"

_RISK_ICON = {"low": "·", "medium": "⚠", "high": "⛔"}


def format_approval_title(*, risk: str, trigger: str) -> str:
    """Smart approval 标题(原 approval_modal._format_title,语义原样迁移):
    trigger 标签按类别格式化。

    标签格式约定:
      hard_rule:X       → [hard rule: X]
      soft_allow:X      → [soft rule: allow X]
      soft_ask:X        → [soft rule: ask X]
      soft_deny:X       → [soft rule: deny X]
      secret:X          → [secret: X]
      tool_level:T=L    → [level: L]
      level:L           → [level: L]
    空 trigger / 未知前缀 → 不附加标签(向后兼容)。"""
    icon = _RISK_ICON.get(risk, "·")
    base = f"{icon} 审批请求 [{risk}]"
    if not trigger:
        return base
    if trigger.startswith("hard_rule:"):
        tag = f"[hard rule: {trigger.split(':', 1)[1]}]"
    elif trigger.startswith("soft_allow:"):
        tag = f"[soft rule: allow {trigger.split(':', 1)[1]}]"
    elif trigger.startswith("soft_ask:"):
        tag = f"[soft rule: ask {trigger.split(':', 1)[1]}]"
    elif trigger.startswith("soft_deny:"):
        tag = f"[soft rule: deny {trigger.split(':', 1)[1]}]"
    elif trigger.startswith("secret:"):
        tag = f"[secret: {trigger.split(':', 1)[1]}]"
    elif trigger.startswith("tool_level:"):
        inner = trigger.split("=", 1)[1] if "=" in trigger else trigger
        tag = f"[level: {inner}]"
    elif trigger.startswith("level:"):
        tag = f"[level: {trigger.split(':', 1)[1]}]"
    else:
        return base
    return f"{base} — {tag}"


class InlineChoice(Vertical):
    """流内单选。options = [(value, label), ...];on_decide(value, feedback) 在决策后回调一次。"""

    DEFAULT_CSS = """
    InlineChoice { height: auto; margin: 0 1 1 1; padding: 0 1; background: $surface; border-left: thick $warning; }
    InlineChoice.risk-low  { border-left: thick $panel; }
    InlineChoice.risk-high { border-left: thick $error; }
    InlineChoice #ic-title { text-style: bold; color: $warning; }
    InlineChoice.risk-high #ic-title { color: $error; }
    InlineChoice #ic-body { color: $foreground; }
    InlineChoice #ic-hint { color: $text-muted; }
    InlineChoice #ic-input { display: none; }
    InlineChoice.-input-mode #ic-input { display: block; }
    """

    can_focus = True

    def __init__(
        self,
        *,
        title: str,
        body: str = "",
        options: list[tuple[str, str]],
        on_decide: Callable[[str, str], None],
        escape_value: str | None = None,
        needs_input: frozenset[str] | set[str] = frozenset(),
        input_placeholder: str = "补充反馈,Enter 提交,Esc 返回",
        risk: str = "medium",
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        if not options:
            raise ValueError("InlineChoice 至少需要一个选项")
        self._title = title
        self._body = body
        self._options = list(options)
        self._on_decide = on_decide
        self._escape_value = escape_value
        self._needs_input = frozenset(needs_input)
        self._input_placeholder = input_placeholder
        self._cursor = 0
        self._decided = False
        self._pending_value: str | None = None   # 进入反馈输入态时挂起的选项值
        self.add_class(f"risk-{risk}" if risk in ("low", "high") else "risk-medium")

    # ── 渲染 ─────────────────────────────────────────────────────────
    def compose(self) -> ComposeResult:
        yield Static(self._title, id="ic-title", markup=False)
        if self._body:
            yield Static(self._body, id="ic-body", markup=False)
        yield Static(self._options_text(), id="ic-options")
        yield Static(self._hint_text(), id="ic-hint", markup=False)
        yield Input(placeholder=self._input_placeholder, id="ic-input")

    def _options_text(self) -> Text:
        t = Text()
        for i, (_, label) in enumerate(self._options):
            cur = i == self._cursor
            t.append("▸ " if cur else "  ", style=f"bold {_ACCENT}")
            t.append(f"{i + 1}. {label}", style=f"bold {_ACCENT}" if cur else _MUTED)
            if i < len(self._options) - 1:
                t.append("\n")
        return t

    def _hint_text(self) -> str:
        esc = " · Esc 拒绝" if self._escape_value else ""
        return f"↑↓ 选择 · ↵ 确认 · 数字直选{esc}"

    def _refresh_options(self) -> None:
        self.query_one("#ic-options", Static).update(self._options_text())

    # ── 生命周期:夺焦 + 铃 ───────────────────────────────────────────
    def on_mount(self) -> None:
        self.focus()
        try:
            self.app.bell()   # 用户要求的到达提示音(终端铃,尊重终端静音设置)
        except Exception:  # noqa: BLE001 — headless/测试环境无铃,静默
            pass

    # ── 键路 ─────────────────────────────────────────────────────────
    async def _on_key(self, event: events.Key) -> None:
        if self._decided:
            return
        key = event.key
        if self.has_class("-input-mode"):
            # 输入态:Enter 由 Input.Submitted 钩子消费;Esc(从 Input 冒泡上来)收起回选项。
            if key == "escape":
                event.stop()
                self._pending_value = None
                self.remove_class("-input-mode")
                self.focus()
            else:
                await super()._on_key(event)
            return
        if key == "up":
            event.stop()
            self._cursor = (self._cursor - 1) % len(self._options)
            self._refresh_options()
        elif key == "down":
            event.stop()
            self._cursor = (self._cursor + 1) % len(self._options)
            self._refresh_options()
        elif key == "enter":
            event.stop()
            self._confirm(self._options[self._cursor][0])
        elif key == "escape" and self._escape_value:
            event.stop()
            self._finish(self._escape_value, "")
        elif key.isdigit() and 1 <= int(key) <= len(self._options):
            event.stop()
            self._cursor = int(key) - 1
            self._refresh_options()
            self._confirm(self._options[self._cursor][0])
        else:
            await super()._on_key(event)

    def _confirm(self, value: str) -> None:
        if value in self._needs_input:
            # 就地展开反馈输入(refine 场景):Enter 提交,Esc 收起回选项。
            self._pending_value = value
            self.add_class("-input-mode")
            self.query_one("#ic-input", Input).focus()
            return
        self._finish(value, "")

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if self._pending_value is not None:
            event.stop()
            self._finish(self._pending_value, event.value.strip())

    # ── 决策落定 ─────────────────────────────────────────────────────
    def _finish(self, value: str, feedback: str) -> None:
        if self._decided:
            return  # 幂等:绝不双发(双发会把 gate.respond 打到已消费的 call_id)
        self._decided = True
        try:
            self._on_decide(value, feedback)
        finally:
            self.remove()
            # 焦点还给主输入框(草稿不丢);测试/异构布局下找不到则静默。
            try:
                self.app.query_one("#prompt").focus()
            except Exception:  # noqa: BLE001
                pass
