# argos/tui/widgets/orders_panel.py
"""OrdersPanel + ConductorSuggestionChoice（TUI v3 spec §12 Conductor 自治面）。

两个组件：
  OrdersPanel             — 常驻指令只读表格（StandingOrder 列表渲染）
  ConductorSuggestionChoice — 主动建议决策卡（InlineChoice 子类）

v3 字形铁律（§12）：
  ⏱ (U+23F1)  schedule 类型行前缀
  ⊙ (U+2299)  file_trigger 类型行前缀
  ◔ (U+25D4)  主动建议标题（等待/扫描四分眼）
  ▸ (U+25B8)  选项光标（由 InlineChoice 继承）
  ◕ (U+25D5)  决策后摘要（阅毕眼，由 InlineChoice._finish 输出）
  ◌ (U+25CC)  忽略/空态摘要
  › (U+203A)  命令回显前缀
  → (U+2192)  action 箭头

禁止字形（v3 铁律）：◎ ● ○ ◐ ◑ ◇ ◆ ▶ •；⊙ 只作 file_trigger 字形，禁作 bullet。
CSS 层：只用 $token 名，绝不硬编码 hex。
Rich Text 层：用下方 _COL_* 常量（注释标注对应 token，与 theme.py 保持同步）。
markup=False：所有含 model/用户/路径文本的 Static 必须关闭 markup 解析。
"""
from __future__ import annotations

from collections.abc import Callable

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Vertical
from textual.widgets import Static

from argos.conductor.orders import StandingOrder
from argos.i18n import t
from argos.protocol.events import ProactiveSuggestionEvent
from argos.tui.widgets.inline_choice import InlineChoice

# ---------------------------------------------------------------------------
# Rich Text 颜色常量（与 theme.py token 一一对应，供 Rich 调用——Rich 不解析 $token）
# CSS DEFAULT_CSS 中继续使用 $token 名。
# ---------------------------------------------------------------------------
_COL_EYE_SOFT   = "#A8854A"   # $eye-soft:  弱强调（order 类型字形，非 chrome）
_COL_EYE        = "#D9A85C"   # $eye:       chrome 强调（▸ 光标）
_COL_INK        = "#C8CCDA"   # $ink:       散文正文
_COL_INK_DIM    = "#7E869C"   # $ink-dim:   次要/utterance 列
_COL_INK_FAINT  = "#6B7494"   # $ink-faint: action 列 / footer
_COL_INK_GHOST  = "#3A4055"   # $ink-ghost: disabled 行整体降级
_COL_PLAN       = "#7AA2F7"   # $plan:      plan-mode 蓝（suggestion 卡边框 + 标题）
_COL_PASS       = "#9ECE6A"   # $pass:      confirm 选项标签
_COL_FAIL       = "#F7768E"   # $fail:      dismiss 选项标签


# ---------------------------------------------------------------------------
# 辅助：StandingOrder 规范化（接受 StandingOrder 或 dict）
# ---------------------------------------------------------------------------

def _normalize_order(obj: StandingOrder | dict) -> StandingOrder:
    """将 daemon GET /orders 返回的 dict 或 StandingOrder 统一为 StandingOrder。"""
    if isinstance(obj, StandingOrder):
        return obj
    return StandingOrder.from_dict(obj)


# ---------------------------------------------------------------------------
# OrdersPanel — 常驻指令只读表格
# ---------------------------------------------------------------------------

class OrdersPanel(Vertical):
    """常驻指令只读渲染面板（/orders 命令结果）。

    接受 StandingOrder 对象列表或 to_dict() 字典列表（兼容 daemon 两路输入）。
    纯展示：无 focus、无键盘交互、无执行动作。
    空态诚实：显示 '无常驻指令'，绝不注入 mock 样本数据。
    Disabled 订单：以 $ink-ghost 降级但不隐藏（诚实不变量）。
    """

    DEFAULT_CSS = """
    OrdersPanel {
        height: auto;
        margin: 0 0 1 0;
        padding: 1 2;
        background: $abyss;
        border: round $hairline-lit;
    }
    OrdersPanel .op-count   { color: $ink; }
    OrdersPanel .op-empty   { color: $ink-faint; }
    OrdersPanel .op-footer  { color: $ink-faint; }
    OrdersPanel .op-echo    { color: $ink-dim; }
    """

    def __init__(
        self,
        *,
        orders: list[StandingOrder | dict],
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        # 规范化为 StandingOrder 列表（内部统一使用强类型）
        self._orders: list[StandingOrder] = [_normalize_order(o) for o in orders]

    # ── 辅助方法（供渲染和测试调用）────────────────────────────────────

    def _count_line(self) -> str:
        """精确 count line 格式: 'standing orders ({n})'。"""
        return f"standing orders ({len(self._orders)})"

    def _empty_state_text(self) -> str:
        """诚实空态文本——绝不注入虚假样本。"""
        return t("widget.orders_empty")

    def _footer_left(self) -> str:
        """footer 左侧精确文本。"""
        return t("widget.orders_footer_left")

    def _footer_right(self) -> str:
        """footer 右侧精确文本。"""
        return "argos/conductor"

    def _order_row_text(self, order: StandingOrder) -> Text:
        """为单条 StandingOrder 生成 Rich Text 行。

        格式（4列）：
          col0 GLYPH   ⏱ / ⊙      $eye-soft
          col1 TRIGGER schedule / trigger_glob 内容  $ink
          col2 UTTERANCE  order.utterance            $ink-dim（disabled → $ink-ghost）
          col3 ACTION    → run / → dream             $ink-faint（disabled → $ink-ghost）

        Disabled 订单：整行以 $ink-ghost 渲染（降级但不隐藏）。
        """
        t = Text()

        if order.enabled:
            glyph_color = _COL_EYE_SOFT
            trigger_color = _COL_INK
            utterance_color = _COL_INK_DIM
            action_color = _COL_INK_FAINT
        else:
            # disabled → 整行 $ink-ghost 降级
            glyph_color = _COL_INK_GHOST
            trigger_color = _COL_INK_GHOST
            utterance_color = _COL_INK_GHOST
            action_color = _COL_INK_GHOST

        # col0: 类型字形（v3 铁律：⏱ schedule / ⊙ file_trigger）
        if order.kind == "schedule":
            t.append("⏱ ", style=glyph_color)
        else:
            t.append("⊙ ", style=glyph_color)

        # col1: trigger 列
        if order.kind == "schedule":
            trigger_label = order.schedule or ""
        else:
            trigger_label = order.trigger_glob or ""

        # 固定宽度 20 字符（近似 152px / 8px=19 → 20 保底）
        t.append(f"{trigger_label:<20}", style=trigger_color)

        # col2: utterance（flex 1fr）
        t.append(f"  {order.utterance}", style=utterance_color)

        # col3: action（→ run / → dream）
        t.append(f"  → {order.action}", style=action_color)

        return t

    # ── Textual 渲染 ──────────────────────────────────────────────────────

    def compose(self) -> ComposeResult:
        """渲染顺序：命令回显 → count line → 订单行（或空态）→ footer。"""
        # 命令回显行（由 app.py 注入，但本 widget 包含后更完整）
        # 只渲染 widget 内容，不重复 app.py 的 › /orders 回显
        # count line
        yield Static(self._count_line(), markup=False, classes="op-count")

        if not self._orders:
            # 诚实空态：绝不注入虚假样本
            yield Static(self._empty_state_text(), markup=False, classes="op-empty")
        else:
            for order in self._orders:
                row = self._order_row_text(order)
                yield Static(row, markup=False)

        # footer（两列合并为一行：左文 + 两空格 + 右归属，全部 $ink-faint）
        footer_text = Text()
        footer_text.append(self._footer_left(), style=_COL_INK_FAINT)
        footer_text.append("  ", style=_COL_INK_FAINT)
        footer_text.append(self._footer_right(), style=_COL_INK_FAINT)
        yield Static(footer_text, markup=False, classes="op-footer")


# ---------------------------------------------------------------------------
# ConductorSuggestionChoice — 主动建议决策卡（InlineChoice 子类）
# ---------------------------------------------------------------------------

class ConductorSuggestionChoice(InlineChoice):
    """主动建议决策卡（§12 Conductor 自治面）。

    继承 InlineChoice 的完整键路机制（↑↓/Enter/数字/Esc/自毁 ◕ 摘要/焦点归还）。
    CSS 覆盖：左边框 $plan（plan-mode 蓝），标题色 $plan。
    标题字形：◔ (U+25D4 scanning quarter-eye)——"等待确认"语义。
    escape_value="dismiss" — Esc = fail-closed = 忽略（Conductor README §197 铁律）。
    requires_confirmation 铁律行永远出现在 _body 中，绝不省略。
    """

    DEFAULT_CSS = """
    ConductorSuggestionChoice {
        height: auto;
        margin: 0 0 1 0;
        padding: 1 2;
        background: $raise;
        border-left: thick $plan;
    }
    ConductorSuggestionChoice #ic-title {
        text-style: bold;
        color: $plan;
    }
    ConductorSuggestionChoice #ic-body  { color: $ink; }
    ConductorSuggestionChoice #ic-hint  { color: $ink-faint; }
    ConductorSuggestionChoice #ic-input { display: none; }
    ConductorSuggestionChoice.-input-mode #ic-input { display: block; }
    """

    # ◔ = U+25D4 CIRCLE WITH UPPER RIGHT QUADRANT BLACK（§12 spec 扫描四分眼）
    # Title is resolved at __init__ time via t() to respect ARGOS_LANG.
    _TITLE_KEY = "widget.conductor_title"

    def __init__(
        self,
        *,
        ev: ProactiveSuggestionEvent,
        on_decide: Callable[[str, str], None],
        **kwargs,
    ) -> None:
        sid8 = ev.suggestion_id[:8]

        # _body: 3 行，每行换行分隔
        #   Line 1: reason_human
        #   Line 2: 建议执行 → <goal>
        #   Line 3: 诚实铁律行（requires_confirmation 永远 True）
        body = (
            f"{ev.reason_human}\n"
            f"{t('widget.conductor_body_suggest', goal=ev.goal)}\n"
            f"{t('widget.conductor_body_confirm_invariant')}"
        )

        # 选项：1 确认执行（confirm），2 忽略（dismiss）
        # label 包含 sid8 以及 /confirm /dismiss 命令提示（视觉稿格式）
        options: list[tuple[str, str]] = [
            ("confirm", t("widget.conductor_option_confirm", sid8=sid8)),
            ("dismiss", t("widget.conductor_option_dismiss", sid8=sid8)),
        ]

        super().__init__(
            title=t(self._TITLE_KEY),
            body=body,
            options=options,
            on_decide=on_decide,
            escape_value="dismiss",     # Esc = fail-closed = 忽略
            risk="medium",              # 边框继承为 $plan，由 DEFAULT_CSS 覆盖
            action_label=t("widget.conductor_action_label"),
            **kwargs,
        )

        # 加 'conductor' CSS 类（wiring 用、测试用，区分其他 InlineChoice 实例）
        self.add_class("conductor")

    def _hint_text(self) -> str:
        """覆盖 hint：Esc = 忽略（不是"拒绝"）。"""
        return t("widget.conductor_hint")
