# argos/tui/widgets/inline_choice.py
"""InlineChoice:流内选择组件(TUI v3 spec §4.7)——替代居中 ModalScreen 的统一审批/决策交互。

挂进 Transcript 流内(mount_block),三个场景复用:
  · 工具审批(once/session/always/deny)
  · 计划决策(approve_start/approve_accept_edits/keep_planning/refine——refine 就地展开反馈输入)
  · 工作流审批(once/always/deny)

交互:mount 时夺焦 + 终端铃(app.bell,用户要求的提示音);↑/↓ 移 ▸ 光标;Enter 确认;
数字 1-9 直选;Esc = escape_value(无则忽略,fail-closed 场景由调用方传 "deny")。
决策后调 on_decide(value, feedback),自毁为一行 "◕ 审批 <action> → <decision>";焦点还给 #prompt。
markup=False / Rich Text 渲染:正文常含 `[...]`(命令参数/preview),绝不当 markup 解析。

v3 字形铁律:
  标题前缀 ◓(半阖眼,等用户决策);完成摘要前缀 ◕(阅毕眼)。
  禁止出现 ◎⊙●○◐◑◇◆▶• 等被处决字形。
  secret 命中副标必须用 ⚠︎(U+26A0+U+FE0E,VS15 强制文本字形)。
"""
from __future__ import annotations

from collections.abc import Callable

from rich.text import Text
from textual import events
from textual.app import ComposeResult
from textual.containers import Vertical
from textual.widgets import Input, Static

# ⚠︎ = U+26A0 UNICODE WARNING SIGN + U+FE0E VARIATION SELECTOR-15(强制文本字形)
_WARNING_SIGN = "⚠︎"


def format_approval_title(*, risk: str, trigger: str) -> str:
    """Smart approval 标题(v3):标题前缀固定 ◓(半阖眼,等用户决策)。

    标签格式约定:
      hard_rule:X       → ◓ 审批请求 [risk] — [hard rule: X]
      soft_allow:X      → ◓ 审批请求 [risk] — [soft rule: allow X]
      soft_ask:X        → ◓ 审批请求 [risk] — [soft rule: ask X]
      soft_deny:X       → ◓ 审批请求 [risk] — [soft rule: deny X]
      secret:X          → ◓ 审批请求 [risk] · ⚠︎ 命中密钥模式 X
      tool_level:T=L    → ◓ 审批请求 [risk] — [level: L]
      level:L           → ◓ 审批请求 [risk] — [level: L]
    空 trigger / 未知前缀 → 不附加标签(向后兼容)。"""
    base = f"◓ 审批请求 [{risk}]"
    if not trigger:
        return base
    if trigger.startswith("hard_rule:"):
        tag = f"[hard rule: {trigger.split(':', 1)[1]}]"
        return f"{base} — {tag}"
    elif trigger.startswith("soft_allow:"):
        tag = f"[soft rule: allow {trigger.split(':', 1)[1]}]"
        return f"{base} — {tag}"
    elif trigger.startswith("soft_ask:"):
        tag = f"[soft rule: ask {trigger.split(':', 1)[1]}]"
        return f"{base} — {tag}"
    elif trigger.startswith("soft_deny:"):
        tag = f"[soft rule: deny {trigger.split(':', 1)[1]}]"
        return f"{base} — {tag}"
    elif trigger.startswith("secret:"):
        # secret 命中:副标用 ⚠︎(VS15) + 密钥名称
        key_name = trigger.split(":", 1)[1]
        return f"{base} · {_WARNING_SIGN} 命中密钥模式 {key_name}"
    elif trigger.startswith("tool_level:"):
        inner = trigger.split("=", 1)[1] if "=" in trigger else trigger
        tag = f"[level: {inner}]"
        return f"{base} — {tag}"
    elif trigger.startswith("level:"):
        tag = f"[level: {trigger.split(':', 1)[1]}]"
        return f"{base} — {tag}"
    else:
        return base


class InlineChoice(Vertical):
    """流内单选。options = [(value, label), ...];on_decide(value, feedback) 在决策后回调一次。

    v3 变化:
    - DEFAULT_CSS 全面迁移到 $token 名(v3 黑曜石之眼 token 体系)。
    - 决策后自毁为一行 "◕ 审批 <action_label> → <decision>" Static(阅毕眼摘要)。
    - action_label 参数用于摘要行;未传则取 options[0][0] 最保守兜底。
    """

    DEFAULT_CSS = """
    InlineChoice { height: auto; margin: 0 0 1 0; padding: 1 2; background: $raise; border-left: thick $unverif; }
    InlineChoice.risk-low  { border-left: thick $hairline-lit; }
    InlineChoice.risk-high { border-left: thick $fail; }
    InlineChoice.risk-plan { border-left: thick $plan; }
    InlineChoice #ic-title { text-style: bold; color: $unverif; }
    InlineChoice.risk-high #ic-title { color: $fail; }
    InlineChoice.risk-plan #ic-title { color: $plan; }
    InlineChoice #ic-body { color: $ink-bright; }
    InlineChoice #ic-hint { color: $ink-faint; }
    InlineChoice #ic-input { display: none; }
    InlineChoice.-input-mode #ic-input { display: block; }
    .ic-summary { color: $ink-faint; }
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
        action_label: str = "",
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
        # action_label 用于决策摘要行;未传则取首选项 value 兜底
        self._action_label = action_label or (options[0][0] if options else "")
        self._cursor = 0
        self._decided = False
        self._pending_value: str | None = None   # 进入反馈输入态时挂起的选项值
        self.add_class(f"risk-{risk}" if risk in ("low", "high", "plan") else "risk-medium")

    # ── 渲染 ─────────────────────────────────────────────────────────
    def compose(self) -> ComposeResult:
        yield Static(self._title, id="ic-title", markup=False)
        if self._body:
            yield Static(self._body, id="ic-body", markup=False)
        yield Static(self._options_text(), id="ic-options")
        yield Static(self._hint_text(), id="ic-hint", markup=False)
        yield Input(placeholder=self._input_placeholder, id="ic-input")

    # ── Rich Text 颜色常量(对应 ARGOS_NIGHT token,用于 Rich Text 渲染)──
    # DEFAULT_CSS 一律用 $token 名;Rich Text style 用 hex(Rich 不解析 $token)
    _COL_EYE       = "#D9A85C"   # $eye: 金系主强调
    _COL_INK_BRIGHT = "#ECEEF5"  # $ink-bright: bold 强调
    _COL_INK_DIM   = "#7E869C"   # $ink-dim: 次要/非选中

    def _options_text(self) -> Text:
        """渲染选项列表:当前项前缀 ▸(U+25B8),非选中项两空格缩进。"""
        t = Text()
        for i, (_, label) in enumerate(self._options):
            cur = i == self._cursor
            # ▸(U+25B8 BLACK RIGHT-POINTING SMALL TRIANGLE)——spec §3 词典字形
            t.append("▸ " if cur else "  ", style=f"bold {self._COL_EYE}")
            t.append(
                f"{i + 1}  {label}",
                style=f"bold {self._COL_INK_BRIGHT}" if cur else self._COL_INK_DIM,
            )
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
        """决策落定:幂等(绝不双发),on_decide 先于自毁。

        自毁流程:
          1. 标记 _decided=True(幂等门禁)
          2. 调 on_decide(value, feedback)(契约3:gate.respond 在此链路里发生)
          3. 在父容器挂载 "◕ 审批 <action> → <decision>" 摘要 Static(阅毕眼,v3)
          4. remove() 自毁本组件
          5. 焦点还给 #prompt(输入草稿不丢)
        """
        if self._decided:
            return  # 幂等:绝不双发(双发会把 gate.respond 打到已消费的 call_id)
        self._decided = True
        try:
            self._on_decide(value, feedback)
        finally:
            # 决策后自毁为一行摘要——◕ 阅毕眼(v3 spec §4.7)
            summary_text = f"◕ 审批 {self._action_label} → {value}"
            parent = self.parent
            try:
                if parent is not None:
                    # mount_widget 是同步挂载;用 call_after_refresh 避免 compose 竞态
                    summary = Static(summary_text, markup=False, classes="ic-summary")
                    parent.mount(summary, after=self)
            except Exception:  # noqa: BLE001 — headless/异构布局下挂载失败静默
                pass
            self.remove()
            # 焦点还给主输入框(草稿不丢);测试/异构布局下找不到则静默。
            try:
                self.app.query_one("#prompt").focus()
            except Exception:  # noqa: BLE001
                pass
