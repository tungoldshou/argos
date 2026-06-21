# argos/tui/widgets/routing_table.py
"""RoutingTable:每任务路由配置表(TUI v3 spec §15)。

只读静态块，挂进 Transcript 流内(log.mount_block)；不可聚焦，无键处理。
渲染内容:
  · › /routing  echo 行
  · 按任务路由 · 8 类别 caption
  · 8 行 category→tier 配置（fixed-width 对齐，tier 按名着色，❂ force confirm 尾缀）
  · /routing set <类别> <档位> 修改  hint
  · 可选历史块（router.history() 最近 10 次决策）
  · 页脚：启发式分类 · 0 token · 异常兜底 simple_read  argos/routing

颜色铁律(spec §15 · 诚实规则 #1/#7):
  cheap   → $cyan      (#7DCFFF)
  default → $ink       (#C8CCDA)
  strong  → $ink-bright(#ECEEF5)
  其他    → $ink        (兜底，不引入新语义色)

force-confirm 尾缀(spec §15 · 诚实规则 #2):
  ❂ force confirm → $unverif (#FF9E64)，必须出现且仅在 is_force_confirm(tier) 时出现。

markup=False 铁律：category 名/tier 名可含 `[...]`，绝不当 Rich markup 解析。
"""
from __future__ import annotations

from typing import Sequence

from rich.text import Text
from textual.widgets import Static

from argos.i18n import t as _t
from argos.routing.categorizer import TaskCategory
from argos.routing.config import RoutingConfig
from argos.routing.resolver import RouteDecision

# ── Rich Text 颜色常量(对应 ARGOS_NIGHT token，Rich 不解析 $token) ──
# DEFAULT_CSS 一律用 $token 名；Rich Text style 用 hex，与 theme.py 严格对齐。
_COL_CYAN        = "#7DCFFF"   # $cyan       — cheap tier
_COL_INK         = "#C8CCDA"   # $ink        — default tier / 散文正文
_COL_INK_BRIGHT  = "#ECEEF5"   # $ink-bright — strong tier
_COL_INK_DIM     = "#7E869C"   # $ink-dim    — category 名 / echo 前缀
_COL_INK_FAINT   = "#525A73"   # $ink-faint  — hint / footer
_COL_UNVERIF     = "#FF9E64"   # $unverif    — ❂ force confirm 尾缀

# 8 类别固定枚举，按 spec 顺序渲染
_CATEGORIES: tuple[TaskCategory, ...] = (
    TaskCategory.PLAN,
    TaskCategory.FILE_EDIT,
    TaskCategory.REFACTOR,
    TaskCategory.TEST_WRITE,
    TaskCategory.VERIFY,
    TaskCategory.LONG_RUN,
    TaskCategory.AUTO_CAPTURE,
    TaskCategory.SIMPLE_READ,
)

# tier 名 → 色十六进制（仅三个已知值；其余兜底 $ink）
_TIER_COLOR: dict[str, str] = {
    "cheap":   _COL_CYAN,
    "default": _COL_INK,
    "strong":  _COL_INK_BRIGHT,
}

# category.value 列宽（left-pad 至 13 chars，与 spec 格式字串一致）
_CAT_COL_WIDTH = 13


def _tier_color(tier: str) -> str:
    """将 tier 名映射到 Rich hex 色字符串；未知名 → 兜底 $ink。"""
    return _TIER_COLOR.get(tier, _COL_INK)


class RoutingTable(Static):
    """每任务路由配置表（只读 Static 块）。

    公开 API（供 app.py wiring 阶段使用）：
      RoutingTable(routing: RoutingConfig, history: list[RouteDecision])
      .routing    → RoutingConfig
      .history    → list[RouteDecision]
      .rendered_text() → rich.text.Text  （测试 + 内部渲染共用）

    挂载：
      await log.mount_block(RoutingTable(routing=router.routing, history=router.history()))
    """

    # DEFAULT_CSS 一律用 $token 名（禁裸 hex）
    DEFAULT_CSS = """
    RoutingTable {
        height: auto;
        margin: 0 0 1 0;
        padding: 1 2;
        background: $stream;
        border: round $border;
    }
    """

    can_focus = False

    def __init__(
        self,
        routing: RoutingConfig,
        history: Sequence[RouteDecision],
        **kwargs,
    ) -> None:
        # markup=False 由 Static 基类 render_str=False；我们直接传 Text 对象
        super().__init__(**kwargs)
        self._routing = routing
        self._history: list[RouteDecision] = list(history)

    # ── 公开属性(wiring 阶段使用) ────────────────────────────────
    @property
    def routing(self) -> RoutingConfig:
        """持有的 RoutingConfig 实例。"""
        return self._routing

    @property
    def history(self) -> list[RouteDecision]:
        """持有的 RouteDecision 列表（run-local，最多 10 条）。"""
        return self._history

    # ── 核心渲染 ─────────────────────────────────────────────────
    def rendered_text(self) -> Text:
        """构建完整的 Rich Text 对象（markup=False 全程 — append 不解析标记）。"""
        t = Text()

        # Row 1: › /routing echo 行
        t.append("› /routing", style=_COL_INK_DIM)
        t.append("\n")

        # Row 2: caption
        t.append(_t("widget.routing_caption"), style=_COL_INK)
        t.append("\n")

        # Row 3..N: 8 category→tier 行
        for cat in _CATEGORIES:
            self._append_category_row(t, cat)

        # set hint 行
        t.append(_t("widget.routing_set_hint"), style=_COL_INK_FAINT)
        t.append("\n")

        # 历史块
        self._append_history_block(t)

        # 页脚（单行，左标签 + 右模块标签）
        t.append(_t("widget.routing_footer_left"), style=_COL_INK_FAINT)
        t.append("  ", style=_COL_INK_FAINT)
        t.append(_t("widget.routing_footer_module"), style=_COL_INK_FAINT)

        return t

    def _append_category_row(self, t: Text, cat: TaskCategory) -> None:
        """追加一行 category→tier（含可选 ❂ force confirm 尾缀）。

        格式（spec §15 verbatim）:
          f"  {cat:<13}→ {tier}" [  ❂ force confirm]
        color:
          cat  → $ink-dim
          → tier → tier-color
          ❂ force confirm → $unverif
        """
        # 解析 tier：by_category 优先，否则 default
        tier = self._routing.by_category.get(cat.value, self._routing.default)

        # 左列：两空格缩进 + category name（左对齐至 _CAT_COL_WIDTH 宽）
        cat_label = f"  {cat.value:<{_CAT_COL_WIDTH}}"
        t.append(cat_label, style=_COL_INK_DIM)

        # 箭头 + tier 名（tier 着色）
        t.append("→ ", style=_COL_INK_DIM)
        t.append(tier, style=_tier_color(tier))

        # force-confirm 尾缀（诚实规则 #2）
        if self._routing.is_force_confirm(tier):
            t.append(_t("widget.routing_force_confirm"), style=_COL_UNVERIF)

        t.append("\n")

    def _append_history_block(self, t: Text) -> None:
        """追加历史决策块（最多 10 条）；无历史则诚实空态。"""
        if not self._history:
            t.append(_t("widget.routing_no_history"), style=_COL_INK_FAINT)
            t.append("\n")
            return

        t.append(_t("widget.routing_history_header"), style=_COL_INK_DIM)
        t.append("\n")

        # spec: f"  step {d.step:3}  cat={d.category.value:13} tool={d.tool or '-':14} → {d.tier:8} ({d.source})"
        for d in self._history[:10]:
            tool_str = d.tool or "-"
            # 各字段均为纯文本，markup=False（tool 名可含方括号）
            line_cat = f"  step {d.step:3}  cat={d.category.value:<13} tool={tool_str:<14} → "
            t.append(line_cat, style=_COL_INK_DIM)
            # tier 着色
            t.append(f"{d.tier:<8}", style=_tier_color(d.tier))
            # source 字段
            t.append(f" ({d.source})", style=_COL_INK_FAINT)
            t.append("\n")

    # ── Textual 渲染入口 ─────────────────────────────────────────
    def render(self) -> Text:
        """Textual 调用：返回 rendered_text()。"""
        return self.rendered_text()
