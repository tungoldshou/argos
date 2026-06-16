# argos/tui/widgets/intent_card_choice.py
"""IntentCardChoice — 意图确认环(TUI v3 spec §09 Intent 确认环)。

在 Transcript 流内渲染 IntentCard 字段网格并等待用户决策。
继承 InlineChoice(键盘路由/光标/自毁完全复用),只覆盖 compose() 和 DEFAULT_CSS。

视觉合约:
  · 左边框 thick $eye(金系,区别于审批卡的橙系 $unverif)
  · 标题 ◉(U+25C9 FISHEYE 注视实瞳)
  · 字段网格:标签列 $ink-faint + EAW 对齐 + 2 空格 gutter
  · 风险药片色阶:高危不可逆→$fail(红) / 普通→$unverif(橙) / 无→$ink-dim 兜底
  · 澄清问 '? ' 前缀,$plan 蓝,最多 3 条
  · 自毁摘要 ◕(U+25D5 阅毕眼) 三分支精确文字

诚实铁律(不可违):
  · Esc = cancel = confirmed=False = 绝不自动执行
  · 风险 pill 禁用 $eye 金色 / $pass 绿色 / $pass-weak 弱绿
  · 无 flag → '(无高危标记)' $ink-dim 兜底,不造 flag
  · computer.* 永远 $fail(高危不可逆)
  · card_json 损坏 → fallback 到 confirmation_text,绝不自动确认
  · edit → confirmed=False,只回填 prompt,不启动 run
"""
from __future__ import annotations

from collections.abc import Callable
from typing import Any

from rich.text import Text
from textual.app import ComposeResult
from textual.widgets import Static

from argos.tui.widgets.inline_choice import InlineChoice

# ── 模块级 hex 色彩常量(与 theme.py token 保持同步,注释标注对应 token)──────
# DEFAULT_CSS 用 $token;Rich Text 用这里的 hex(Rich 不解析 $token)
_COL_EYE         = "#D9A85C"   # $eye:金系主强调(标题 ◉)
_COL_EYE_GLOW    = "#F0C078"   # $eye-glow:高亮
_COL_INK_BRIGHT  = "#ECEEF5"   # $ink-bright:goal / 当前选项
_COL_INK         = "#C8CCDA"   # $ink:deliverable / constraints / not_doing
_COL_INK_DIM     = "#7E869C"   # $ink-dim:次要 / 无 flag 兜底
_COL_INK_FAINT   = "#525A73"   # $ink-faint:标签列 / 提示
_COL_PLAN        = "#7AA2F7"   # $plan:澄清问 '? ' 行
_COL_UNVERIF     = "#FF9E64"   # $unverif:普通风险 pill(橙)
_COL_UNVERIF_DEEP = "#9A6E2E"  # $unverif-deep:风险块左缘(暗档)
_COL_FAIL        = "#F7768E"   # $fail:高危不可逆 pill(红)
_COL_HAIRLINE_LIT = "#2E3142"  # $hairline-lit

# ── 高危不可逆 flag 集合(来自 argos/intent/engine.py _RISK_WORDS 子集)────────
# computer.* 前缀由 _is_high_irreversible() 动态检测,不写入此集合
_HIGH_IRREVERSIBLE_FLAGS: frozenset[str] = frozenset({
    "delete_files",
    "format_disk",
    "financial_transfer",
    "purchase",
    "uninstall",
    "elevated_privilege",
})

# 固定三选项(value / 显示标签)
_OPTIONS: list[tuple[str, str]] = [
    ("confirm", "确认开始"),
    ("edit",    "修改目标"),
    ("cancel",  "取消"),
]

# 决策摘要精确文字表
_SUMMARY_MAP: dict[str, str] = {
    "confirm": "◕ 意图确认 → 已确认 · 转为 run",
    "edit":    "◕ 意图确认 → 修改目标 · 已取回到输入",
    "cancel":  "◕ 意图确认 → 已取消 · 未执行任何动作",
}


def _is_high_irreversible(flag: str) -> bool:
    """判断 flag 是否属于高危不可逆集合(含 computer.* 前缀)。"""
    return flag in _HIGH_IRREVERSIBLE_FLAGS or flag.startswith("computer_")


def _eaw_len(s: str) -> int:
    """计算字符串的 EAW 终端显示宽度(CJK 字符算 2 列)。

    使用 Rich 内置的 cell_len 而不是自实现,避免 unicodedata 边界差异。
    """
    # Text.cell_len 是 Rich 的官方 EAW 计算接口
    return Text(s).cell_len


def _label_pad(label: str, target_display_width: int = 4) -> str:
    """将标签右填充到 target_display_width 显示列,再加 2 空格 gutter。

    CJK 字符占 2 列,纯 ASCII 占 1 列。
    目标显示宽度 = 4(spec:所有标签对齐到 4 显示列)。
    """
    cur = _eaw_len(label)
    pad = max(0, target_display_width - cur)
    return label + " " * pad + "  "   # 填充到 4 列 + 2 空格 gutter


def _field_row(label: str, value: str, value_color: str) -> Text:
    """渲染一行字段(标签列 $ink-faint + value 列指定色)。

    返回 Rich Text,markup=False 语义(不调 Text.from_markup)。
    """
    t = Text()
    padded_label = _label_pad(label)
    t.append(padded_label, style=_COL_INK_FAINT)
    t.append(value, style=value_color)
    return t


def _risk_pills(flags: tuple[str, ...]) -> Text:
    """渲染风险药片行。

    空 flags → 返回 '(无高危标记)' $ink-dim 兜底文字(诚实:没有捏造的 flag)。
    普通 flag → $unverif 橙色 chip。
    高危不可逆 flag(含 computer.*) → $fail 红色 chip。
    绝不使用 $eye 金色或 $pass/$pass-weak 绿色。
    """
    t = Text()
    if not flags:
        t.append("(无高危标记)", style=_COL_INK_DIM)
        return t
    first = True
    for flag in flags:
        if not first:
            t.append(" ")
        first = False
        color = _COL_FAIL if _is_high_irreversible(flag) else _COL_UNVERIF
        t.append(f" {flag} ", style=color)
    return t


class IntentCardChoice(InlineChoice):
    """意图确认环:字段网格决策卡(TUI v3 screen 09)。

    继承 InlineChoice 的完整键盘机制(↑↓/Enter/数字直选/Esc fail-closed)。
    覆盖:
      - compose():插入金色标题 + 字段网格 + 澄清问,再接父类 #ic-options/#ic-hint
      - DEFAULT_CSS:左边框改为 thick $eye(金系意图卡)
      - _finish():拦截后写入精确摘要文字,再调父类流程

    构造参数:
      card_json          IntentCard.asdict() 序列化字典(来自 IntentConfirmRequest.card_json)
      confirmation_text  fallback 文本(card_json 损坏时显示)
      risk_flags         ev.risk_flags(card_json 无 risk_flags 字段时使用)
      on_decide          决策回调 (value: str, feedback: str) -> None
    """

    DEFAULT_CSS = """
    IntentCardChoice {
        height: auto;
        margin: 0 0 1 0;
        padding: 1 2;
        background: $raise;
        border-left: thick $eye;
    }
    IntentCardChoice #ic-title { text-style: bold; color: $eye; }
    IntentCardChoice #ic-hint  { color: $ink-faint; }
    IntentCardChoice #ic-body  { color: $ink-dim; }
    """

    def __init__(
        self,
        *,
        card_json: dict[str, Any],
        confirmation_text: str,
        risk_flags: tuple[str, ...],
        on_decide: Callable[[str, str], None],
        **kwargs,
    ) -> None:
        # 解析 card_json,失败回退到 fallback 模式
        self._card: dict[str, Any] | None = self._parse_card_json(card_json)
        self._fallback_text = confirmation_text
        # ev.risk_flags 作为备用(card_json 有 risk_flags 时优先使用 card_json 的)
        self._ev_risk_flags = risk_flags

        # 从 card_json 提取有效的 risk_flags(优先 card_json,其次 ev.risk_flags)
        effective_risk = self._effective_risk_flags()

        # 根据 risk_flags 决定 risk 等级(高危不可逆→high,有任意 flag→medium,无→low)
        risk_level = self._compute_risk_level(effective_risk)

        super().__init__(
            title="◉ 意图确认 — 执行前回显",
            body="",                          # body 不用,字段网格替代
            options=_OPTIONS,
            on_decide=on_decide,
            escape_value="cancel",            # Esc fail-closed 铁律
            risk=risk_level,
            action_label="意图确认",
            **kwargs,
        )

    # ── 解析辅助 ─────────────────────────────────────────────────────────────

    @staticmethod
    def _parse_card_json(card_json: dict[str, Any]) -> dict[str, Any] | None:
        """尝试从 card_json 提取必需字段 goal。失败→返回 None(触发 fallback)。"""
        if not isinstance(card_json, dict):
            return None
        if "goal" not in card_json:
            return None
        return card_json

    def _effective_risk_flags(self) -> tuple[str, ...]:
        """card_json.risk_flags 优先;card_json 中无该键则用 ev.risk_flags。

        注意:card_json.risk_flags=[] 是明确的"无 flag",应优先于 ev.risk_flags。
        ev.risk_flags 只在 card_json 完全没有 risk_flags 键时作为备用。
        """
        if self._card is not None:
            # 键存在(哪怕值为空列表):用 card_json 的值
            if "risk_flags" in self._card:
                raw = self._card["risk_flags"]
                return tuple(raw) if raw else ()
            # card_json 没有 risk_flags 键:用 ev.risk_flags
            return self._ev_risk_flags
        return self._ev_risk_flags

    @staticmethod
    def _compute_risk_level(flags: tuple[str, ...]) -> str:
        """推导 InlineChoice risk 等级:高危→'high',有任意 flag→'medium',无→'low'。"""
        if not flags:
            return "low"
        if any(_is_high_irreversible(f) for f in flags):
            return "high"
        return "medium"

    # ── 字段网格构建 ─────────────────────────────────────────────────────────

    def _build_field_rows(self) -> list[Text]:
        """按规范顺序构建字段网格行列表(供 compose 和测试共用)。

        card_json 损坏时只返回 fallback 文本行。
        """
        if self._card is None:
            # fallback:渲染 confirmation_text 作为 $ink-dim 单行
            t = Text()
            t.append(self._fallback_text, style=_COL_INK_DIM)
            return [t]

        rows: list[Text] = []

        # 目标(必渲)
        goal = str(self._card.get("goal", ""))
        rows.append(_field_row("目标", goal, _COL_INK_BRIGHT))

        # 交付物(非空才渲)
        deliverable = str(self._card.get("deliverable", "") or "")
        if deliverable:
            rows.append(_field_row("交付物", deliverable, _COL_INK))

        # 约束(非空才渲)
        constraints = self._card.get("constraints", ()) or ()
        if constraints:
            joined = "、".join(str(c) for c in constraints)   # 、U+3001
            rows.append(_field_row("约束", joined, _COL_INK))

        # 不做(非空才渲)
        not_doing = self._card.get("not_doing", ()) or ()
        if not_doing:
            joined = "、".join(str(n) for n in not_doing)
            rows.append(_field_row("不做", joined, _COL_INK))

        # 风险(始终渲染:有→药片行,无→dim 兜底,铁律)
        effective_flags = self._effective_risk_flags()
        risk_text = _risk_pills(effective_flags)
        label_part = Text()
        label_part.append(_label_pad("风险"), style=_COL_INK_FAINT)
        label_part.append_text(risk_text)
        rows.append(label_part)

        return rows

    def _build_question_rows(self) -> list[Text]:
        """构建澄清问行列表(最多 3 条,前缀 '? ',$plan 蓝)。

        card_json 损坏时返回空列表(无需澄清)。
        """
        if self._card is None:
            return []
        questions = list(self._card.get("questions", ()) or ())
        result: list[Text] = []
        for q in questions[:3]:    # cap at 3
            t = Text()
            t.append("? " + str(q), style=_COL_PLAN)
            result.append(t)
        return result

    # ── 决策摘要 ─────────────────────────────────────────────────────────────

    def _intent_summary(self, value: str) -> str:
        """返回决策摘要精确文字(◕ 阅毕眼三分支)。"""
        return _SUMMARY_MAP.get(value, f"◕ 意图确认 → {value}")

    # ── compose 覆盖 ──────────────────────────────────────────────────────────

    def compose(self) -> ComposeResult:
        """覆盖 InlineChoice.compose():

        字段网格 + 澄清问 + 父类 #ic-options/#ic-hint。
        按 spec 顺序:
          ROW 1 — 标题(◉)
          ROW 2..N — 字段网格(via Static, markup=False)
          ROW S — 空行(间隔)
          ROW Q — 澄清问(via Static, markup=False)
          ROW O — 选项(InlineChoice #ic-options)
          ROW H — 提示(InlineChoice #ic-hint)
        """
        # ROW 1: 标题
        yield Static(self._title, id="ic-title", markup=False)

        # ROW 2..N: 字段网格
        for row_text in self._build_field_rows():
            yield Static(row_text, markup=False)

        # ROW S: 间隔空行
        yield Static("", markup=False)

        # ROW Q: 澄清问(若有)
        for q_text in self._build_question_rows():
            yield Static(q_text, markup=False)

        # ROW O: 选项(复用 InlineChoice 的 _options_text())
        yield Static(self._options_text(), id="ic-options")

        # ROW H: 提示
        yield Static(self._hint_text(), id="ic-hint", markup=False)

    # ── 提示文字覆盖(spec 精确文字 + Esc 取消)──────────────────────────────

    def _hint_text(self) -> str:
        """覆盖 InlineChoice._hint_text():返回 spec 精确提示文字。

        spec ROW H 精确文字:"↑↓ 选择 · ↵ 确认 · 数字直选 · Esc 取消"
        """
        return "↑↓ 选择 · ↵ 确认 · 数字直选 · Esc 取消"

    # ── _finish 覆盖(精确摘要文字)────────────────────────────────────────────

    def _finish(self, value: str, feedback: str) -> None:
        """覆盖 _finish:把父类 '◕ 审批 ...' 摘要替换为意图卡精确文字。

        策略:先标记已决,调 on_decide,再手工挂载精确摘要 + 自毁。
        注意:直接复用父类除 summary_text 外的全部逻辑(幂等门禁/挂载/focus)。
        """
        if self._decided:
            return
        self._decided = True
        try:
            self._on_decide(value, feedback)
        finally:
            summary_text = self._intent_summary(value)
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
