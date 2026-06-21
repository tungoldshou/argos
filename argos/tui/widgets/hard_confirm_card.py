# argos/tui/widgets/hard_confirm_card.py
"""HardConfirmCard:Computer use 硬确认卡(TUI v3 spec §16)。

仅在 computer.* 工具触发审批门时挂载。
继承 InlineChoice,强制覆盖:
  · risk='high'(不可由调用方降级)
  · escape_value='deny'(Esc = 拒绝,fail-closed)
  · 固定 2 选项:[('once','仅此一次'), ('deny','拒绝')]——不提供 session/always
  · 标题 "⛔ 计算机控制 · 硬确认 [high · 不可逆]"(⛔ U+26D4,非 ◓)
  · _options_text 覆盖:deny 选项显示数字 '4'(非 '2')
  · compose 插入 #hc-gov 治理注释 + #hc-foot 页脚不变量

诚实铁律:
  1. risk 恒为 'high';调用方无法传入低 risk(构造函数不接受 risk 参数)。
  2. Esc/超时 = deny(escape_value 硬编码)。
  3. 标题含 '[high · 不可逆]' + ⛔——绝不用 ◓ 软审批字眼。
  4. 选项仅 once/deny;不可逆全局动作绝不授予 session/always。
  5. deny 数字标签为 '4'(非 '2')——与 spec 视觉稿一致。
  6. body/governance/footer 三个 Static 均 markup=False(body 含 [...] 会崩)。

CSS 规则:DEFAULT_CSS 仅用 $token 名,无裸 hex;
Rich Text 样式使用模块级 hex 常量,注明对应 $token。
"""
from __future__ import annotations

from collections.abc import Callable

from rich.text import Text
from textual.app import ComposeResult
from textual.widgets import Static

from argos.i18n import t
from argos.tui.widgets.inline_choice import InlineChoice

# ── Rich Text 颜色常量(对应 ARGOS_NIGHT token,用于 Rich Text 渲染)──────────
# DEFAULT_CSS 一律用 $token 名;Rich Text style 用 hex(Rich 不解析 $token)
_COL_FAIL       = "#F7768E"   # $fail: verdict failed;唯一的红
_COL_EYE        = "#D9A85C"   # $eye: chrome 主强调(金)
_COL_INK_BRIGHT = "#ECEEF5"   # $ink-bright: bold 强调
_COL_INK_DIM    = "#7E869C"   # $ink-dim: 次要/非选中
_COL_INK_FAINT  = "#525A73"   # $ink-faint: 键提示/空态/页脚

# ── 选项编号映射(spec:deny 显示 '4',非 '2')──────────────────────────────────
# value → 显示数字标签(不用 i+1 自动编号)
_OPTION_DIGIT: dict[str, str] = {
    "once": "1",
    "deny": "4",
}


def _body_line(
    action: str,
    *,
    x: int | None,
    y: int | None,
    description: str,
    text: str | None,
    app: str | None,
) -> str:
    """构造 body 行字符串。

    含坐标(x/y 均非 None):f"{action} ({x}, {y}) — {description}"
    无坐标(screenshot/open_app/type_text/key 等):f"{action} — {description}"
    — = U+2014 EM DASH(spec 铁律)。
    """
    if x is not None and y is not None:
        return f"{action} ({x}, {y}) — {description}"
    return f"{action} — {description}"


class HardConfirmCard(InlineChoice):
    """Computer use 硬确认卡(screen 16)。

    公开构造签名::

        HardConfirmCard(
            action: str,            # 能力名,如 'computer_click'
            x: int | None,          # ComputerAction.x
            y: int | None,          # ComputerAction.y
            description: str,       # ApprovalRequest.description(人话)
            on_decide: Callable[[str, str], None],
            text: str | None = None,   # ComputerAction.text(type_text/key/scroll)
            app: str | None = None,    # ComputerAction.app(open_app)
        )

    决策值:
      'once'  → 本次批准
      'deny'  → 拒绝(Esc 也映射到此值)

    挂载方式:通过 app._enqueue_choice(lambda: HardConfirmCard(...)) 进入 FIFO 队列。
    不接受 risk/escape_value 参数(二者硬编码,调用方不可覆盖)。
    """

    # 硬编码静态文字常量(精确匹配 spec,不可参数化) — i18n via property
    @property
    def _GOVERNANCE_TEXT(self) -> str:  # type: ignore[override]
        return t("hardconfirm.governance")

    @property
    def _FOOTER_TEXT(self) -> str:  # type: ignore[override]
        return t("hardconfirm.footer")

    DEFAULT_CSS = """
    HardConfirmCard #hc-gov { color: $ink-faint; }
    HardConfirmCard #hc-foot { color: $ink-faint; margin-top: 1; }
    """

    def __init__(
        self,
        *,
        action: str,
        x: int | None,
        y: int | None,
        description: str,
        on_decide: Callable[[str, str], None],
        text: str | None = None,
        app: str | None = None,
        **kwargs,
    ) -> None:
        """构造 HardConfirmCard。

        risk 硬编码为 'high';escape_value 硬编码为 'deny'。
        调用方只需传 action/x/y/description/on_decide。
        """
        body = _body_line(action, x=x, y=y, description=description, text=text, app=app)
        # action_label 用于 _finish 摘要行("◕ 审批 {action_label} → {value}")
        super().__init__(
            title=t("hardconfirm.title"),
            body=body,
            options=[
                ("once", t("hardconfirm.option_once")),
                ("deny", t("hardconfirm.option_deny")),
            ],
            on_decide=on_decide,
            escape_value="deny",
            risk="high",
            action_label=action,
            **kwargs,
        )

    # ── 选项渲染覆盖:deny 显示 '4',非 '2' ─────────────────────────────────
    def _options_text(self) -> Text:
        """覆盖 InlineChoice._options_text:deny 选项显示数字 '4'。

        保持 ▸ 光标颜色 $eye、cursor/non-cursor 明暗对比等父类约定不变。
        """
        t = Text()
        for i, (value, label) in enumerate(self._options):
            cur = i == self._cursor
            digit = _OPTION_DIGIT.get(value, str(i + 1))
            # ▸ (U+25B8)——spec §3 词典字形;颜色 $eye
            t.append("▸ " if cur else "  ", style=f"bold {_COL_EYE}")
            t.append(
                f"{digit}  {label}",
                style=f"bold {_COL_INK_BRIGHT}" if cur else _COL_INK_DIM,
            )
            if i < len(self._options) - 1:
                t.append("\n")
        return t

    # ── 数字直选键映射(1→index 0 / 4→index 1;其余忽略) ─────────────────────
    def _digit_to_option_index(self, digit: str) -> int | None:
        """将键盘数字映射到选项索引。

        spec 铁律:键 '1' → once(index 0);键 '4' → deny(index 1)。
        其余数字(2/3/5…9)返回 None(忽略,不选任何选项)。
        """
        mapping = {"1": 0, "4": 1}
        return mapping.get(digit)

    # ── 键路覆盖:数字直选用自定义映射 ──────────────────────────────────────
    async def _on_key(self, event) -> None:  # type: ignore[override]
        """覆盖 _on_key:数字直选用 _digit_to_option_index 映射。

        ↑/↓/Enter/Esc 路径不变(父类处理)。
        数字 '1' → once, '4' → deny;其余数字吞掉(不传父类 i+1 逻辑)。
        """
        if self._decided:
            return
        key = event.key
        if key.isdigit():
            event.stop()
            idx = self._digit_to_option_index(key)
            if idx is not None:
                self._cursor = idx
                self._refresh_options()
                self._confirm(self._options[self._cursor][0])
            # 其余数字忽略
            return
        # 非数字键交父类处理(↑/↓/Enter/Esc/_input-mode)
        await super()._on_key(event)

    # ── _finish 覆盖:headless/无 App 环境容错 ──────────────────────────────
    def _finish(self, value: str, feedback: str) -> None:
        """覆盖 _finish:幂等,self.remove() 在无 App 环境下静默降级。

        父类 InlineChoice._finish 的 self.remove() 在 headless/测试环境下
        抛 NoActiveAppError。本覆盖在 try/except 内包裹,保证:
          1. 幂等门禁(_decided guard)
          2. on_decide 在自毁前调用
          3. 摘要 Static 挂载(父容器存在时)
          4. self.remove() / focus 失败时静默(headless 容错)
        """
        if self._decided:
            return
        self._decided = True
        try:
            self._on_decide(value, feedback)
        finally:
            summary_text = t("hardconfirm.finish_summary", action_label=self._action_label, value=value)
            parent = self.parent
            try:
                if parent is not None:
                    summary = Static(summary_text, markup=False, classes="ic-summary")
                    parent.mount(summary, after=self)
            except Exception:  # noqa: BLE001
                pass
            try:
                self.remove()
            except Exception:  # noqa: BLE001 — headless/无 App 环境静默
                pass
            try:
                self.app.query_one("#prompt").focus()
            except Exception:  # noqa: BLE001
                pass

    # ── compose 覆盖:插入治理注释 + 页脚不变量 ──────────────────────────────
    def compose(self) -> ComposeResult:
        """在父类 compose 基础上插入治理注释(#hc-gov)和页脚不变量(#hc-foot)。

        布局顺序(从上到下):
          1. #ic-title  — 标题(父类,markup=False)
          2. #ic-body   — body 行(父类,markup=False)
          3. #hc-gov    — 治理注释(新增,markup=False)
          4. #ic-options — 选项列表(父类 Rich Text)
          5. #hc-foot   — 页脚不变量(新增,markup=False)
          6. #ic-hint   — 键提示(父类,markup=False)
          7. #ic-input  — 反馈输入框(父类,隐藏)
        """
        from textual.widgets import Input
        from textual.widgets import Static as _Static

        # 标题(markup=False — spec 铁律)
        yield _Static(self._title, id="ic-title", markup=False)
        # body(markup=False — body 含 [...] 会崩)
        if self._body:
            yield _Static(self._body, id="ic-body", markup=False)
        # 治理注释(markup=False)
        yield _Static(self._GOVERNANCE_TEXT, id="hc-gov", markup=False)
        # 选项(Rich Text,由 _options_text() 渲染)
        yield _Static(self._options_text(), id="ic-options")
        # 页脚不变量(markup=False)
        yield _Static(self._FOOTER_TEXT, id="hc-foot", markup=False)
        # 键提示(markup=False)
        yield _Static(self._hint_text(), id="ic-hint", markup=False)
        # 反馈输入框(本 widget 不用,隐藏;保留父类结构)
        yield Input(placeholder=self._input_placeholder, id="ic-input")
