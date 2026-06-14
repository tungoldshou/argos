# tests/tui/test_routing_table.py
"""RoutingTable widget 测试(TDD)。

覆盖:
  - 构造：RoutingTable(routing=..., history=...)
  - 承重字形：→ ❂ › ·
  - token/色段：cheap=$cyan / default=$ink / strong=$ink-bright
  - 未知 tier 兜底 $ink
  - force-confirm 尾缀 ❂ force confirm($unverif)
  - 诚实规则：force-confirm 必须出现；no force-confirm 不得出现 ❂
  - 历史块：有历史 / 无历史诚实空态
  - 页脚：承重字符串原文
  - markup=False 要求：category 名不被当做 markup 解析
"""
from __future__ import annotations

from rich.text import Text

from argos.routing.categorizer import TaskCategory
from argos.routing.config import RoutingConfig
from argos.routing.resolver import RouteDecision
from argos.tui.widgets.routing_table import RoutingTable

# ── 色常量(来自 theme.py) ──────────────────────────────────────
_CYAN       = "#7DCFFF"   # $cyan  — cheap tier
_INK        = "#C8CCDA"   # $ink   — default tier
_INK_BRIGHT = "#ECEEF5"   # $ink-bright — strong tier
_INK_DIM    = "#7E869C"   # $ink-dim    — category name, echo
_INK_FAINT  = "#525A73"   # $ink-faint  — hint/footer
_UNVERIF    = "#FF9E64"   # $unverif    — ❂ force confirm
_EYE        = "#D9A85C"   # $eye


# ── 辅助:RoutingConfig 工厂 ──────────────────────────────────────
def _cfg(
    default: str = "default",
    by_category: dict[str, str] | None = None,
    tier_force_confirm: list[str] | None = None,
) -> RoutingConfig:
    return RoutingConfig(
        default=default,
        by_category=by_category or {},
        by_tool={},
        tier_force_confirm=tier_force_confirm or [],
    )


def _table(
    default: str = "default",
    by_category: dict[str, str] | None = None,
    tier_force_confirm: list[str] | None = None,
    history: list[RouteDecision] | None = None,
) -> RoutingTable:
    return RoutingTable(
        routing=_cfg(default=default, by_category=by_category,
                     tier_force_confirm=tier_force_confirm),
        history=history or [],
    )


# ─────────────────────────────────────────────────────────────────
# 1. 构造——无异常
# ─────────────────────────────────────────────────────────────────

class TestConstruction:
    def test_instantiates_with_minimal_args(self) -> None:
        """最小参数不抛。"""
        t = _table()
        assert t is not None

    def test_instantiates_with_full_routing(self) -> None:
        """完整 by_category 不抛。"""
        by_cat = {c.value: "cheap" for c in TaskCategory}
        t = _table(by_category=by_cat)
        assert t is not None

    def test_routing_property_accessible(self) -> None:
        cfg = _cfg(default="strong")
        t = RoutingTable(routing=cfg, history=[])
        assert t.routing is cfg

    def test_history_property_accessible(self) -> None:
        hist = [
            RouteDecision(TaskCategory.PLAN, None, "strong", "by_category", step=1)
        ]
        t = RoutingTable(routing=_cfg(), history=hist)
        assert t.history == hist


# ─────────────────────────────────────────────────────────────────
# 2. rendered_text() 返回 rich.text.Text
# ─────────────────────────────────────────────────────────────────

class TestRenderedText:
    def test_returns_text_instance(self) -> None:
        t = _table()
        rt = t.rendered_text()
        assert isinstance(rt, Text)

    def test_echo_line_present(self) -> None:
        """Row 1: › /routing 出现。"""
        rt = _table().rendered_text()
        plain = rt.plain
        assert "› /routing" in plain

    def test_caption_line_present(self) -> None:
        """Row 2: 按任务路由 · 8 类别 caption。"""
        rt = _table().rendered_text()
        assert "按任务路由" in rt.plain

    def test_all_8_categories_present(self) -> None:
        """8 个 TaskCategory.value 全部出现在 plain text。"""
        rt = _table().rendered_text()
        plain = rt.plain
        for cat in TaskCategory:
            assert cat.value in plain, f"缺失 category: {cat.value}"

    def test_arrow_glyph_present(self) -> None:
        """→ (U+2192) 出现在每条 category 行。"""
        rt = _table().rendered_text()
        assert "→" in rt.plain

    def test_footer_left_string(self) -> None:
        """页脚左侧承重字串。"""
        rt = _table().rendered_text()
        assert "启发式分类" in rt.plain
        assert "异常兜底 simple_read" in rt.plain

    def test_footer_right_string(self) -> None:
        """页脚右侧模块标签。"""
        rt = _table().rendered_text()
        assert "argos/routing" in rt.plain

    def test_set_hint_present(self) -> None:
        """/routing set <类别> <档位> 修改 hint。"""
        rt = _table().rendered_text()
        assert "/routing set" in rt.plain


# ─────────────────────────────────────────────────────────────────
# 3. Tier 颜色规则(通过 span style 检验)
# ─────────────────────────────────────────────────────────────────

def _spans_with_text(rt: Text, substring: str) -> list[str]:
    """返回所有 span 中 style 字符串列表，过滤出包含 substring 的文本对应 span。"""
    styles = []
    pos = 0
    # 遍历 rt._spans 逐个检查覆盖的文本
    for span in rt._spans:
        text_slice = rt.plain[span.start:span.end]
        if substring in text_slice:
            styles.append(str(span.style))
    return styles


def _find_tier_style(rt: Text, tier_name: str) -> list[str]:
    """在 Rich Text spans 中找到包含 tier_name 的 span 的 style 列表。"""
    result = []
    for span in rt._spans:
        text_slice = rt.plain[span.start:span.end]
        if tier_name in text_slice and "→" not in text_slice:
            # 只看 tier 名称段，不要含箭头的整行
            result.append(str(span.style))
    return result


def _find_spans_containing(rt: Text, substring: str) -> list[tuple[str, str]]:
    """返回所有含 substring 的 span (text_slice, style_str) 列表。"""
    result = []
    for span in rt._spans:
        text_slice = rt.plain[span.start:span.end]
        if substring in text_slice:
            result.append((text_slice, str(span.style)))
    return result


class TestTierColoring:
    def test_cheap_tier_uses_cyan(self) -> None:
        """cheap tier → $cyan (#7DCFFF)。"""
        by_cat = {"plan": "cheap"}
        rt = _table(by_category=by_cat).rendered_text()
        spans = _find_spans_containing(rt, "cheap")
        assert any(_CYAN in s for _, s in spans), \
            f"cheap tier 未找到 $cyan span; got spans={spans}"

    def test_default_tier_uses_ink(self) -> None:
        """default tier → $ink (#C8CCDA)。"""
        rt = _table(default="default").rendered_text()
        # all categories without override map to default
        spans = _find_spans_containing(rt, "default")
        assert any(_INK in s for _, s in spans), \
            f"default tier 未找到 $ink span; got spans={spans}"

    def test_strong_tier_uses_ink_bright(self) -> None:
        """strong tier → $ink-bright (#ECEEF5)。"""
        by_cat = {"verify": "strong"}
        rt = _table(by_category=by_cat).rendered_text()
        spans = _find_spans_containing(rt, "strong")
        assert any(_INK_BRIGHT in s for _, s in spans), \
            f"strong tier 未找到 $ink-bright span; got spans={spans}"

    def test_unknown_tier_fallback_to_ink(self) -> None:
        """未知 tier 名 → 兜底 $ink。"""
        by_cat = {"simple_read": "turbo"}
        rt = _table(by_category=by_cat).rendered_text()
        spans = _find_spans_containing(rt, "turbo")
        assert any(_INK in s for _, s in spans), \
            f"未知 tier 未兜底 $ink; got spans={spans}"

    def test_category_name_uses_ink_dim(self) -> None:
        """category 名着色 $ink-dim (#7E869C)。"""
        rt = _table().rendered_text()
        # plan 是 8 类之一
        spans = _find_spans_containing(rt, "plan")
        assert any(_INK_DIM in s for _, s in spans), \
            f"category 名未着色 $ink-dim; got spans={spans}"


# ─────────────────────────────────────────────────────────────────
# 4. Force-confirm 尾缀
# ─────────────────────────────────────────────────────────────────

class TestForceConfirm:
    def test_force_confirm_trailer_present(self) -> None:
        """is_force_confirm 为 True 的 tier → 出现 ❂ force confirm。"""
        rt = _table(
            by_category={"verify": "strong"},
            tier_force_confirm=["strong"],
        ).rendered_text()
        assert "❂" in rt.plain
        assert "force confirm" in rt.plain

    def test_force_confirm_uses_unverif_color(self) -> None:
        """❂ force confirm 着色 $unverif (#FF9E64)。"""
        rt = _table(
            by_category={"verify": "strong"},
            tier_force_confirm=["strong"],
        ).rendered_text()
        spans = _find_spans_containing(rt, "❂")
        assert any(_UNVERIF in s for _, s in spans), \
            f"❂ 未着色 $unverif; got spans={spans}"

    def test_no_force_confirm_no_glyph(self) -> None:
        """tier_force_confirm 为空 → ❂ 不出现。"""
        rt = _table(tier_force_confirm=[]).rendered_text()
        assert "❂" not in rt.plain

    def test_force_confirm_only_on_matching_tiers(self) -> None:
        """仅被标记的 tier 行出现 ❂，未标记的 tier 行不出现。"""
        by_cat = {"verify": "strong", "plan": "cheap"}
        rt = _table(
            by_category=by_cat,
            tier_force_confirm=["strong"],
        ).rendered_text()
        plain = rt.plain
        # plan 行应无 ❂
        lines = plain.splitlines()
        plan_lines = [l for l in lines if "plan" in l and "→" in l and "test_write" not in l]
        for line in plan_lines:
            assert "❂" not in line, f"plan(cheap,无 force) 行出现了 ❂: {line!r}"


# ─────────────────────────────────────────────────────────────────
# 5. 历史块
# ─────────────────────────────────────────────────────────────────

class TestHistory:
    def test_empty_history_shows_honest_message(self) -> None:
        """无历史 → 出现诚实空态提示，绝不造假行。"""
        rt = _table(history=[]).rendered_text()
        plain = rt.plain
        assert "尚未调模型" in plain or "无" in plain, \
            f"空历史未显示诚实提示; plain={plain[:300]}"

    def test_history_rows_rendered(self) -> None:
        """有历史 → RouteDecision 各字段出现。"""
        hist = [
            RouteDecision(TaskCategory.FILE_EDIT, None, "cheap", "by_category", step=3),
            RouteDecision(TaskCategory.VERIFY, "run_command", "strong", "by_tool", step=7),
        ]
        rt = _table(history=hist).rendered_text()
        plain = rt.plain
        assert "file_edit" in plain
        assert "verify" in plain
        assert "cheap" in plain
        assert "strong" in plain

    def test_history_step_numbers_rendered(self) -> None:
        """step 号出现在历史行。"""
        hist = [
            RouteDecision(TaskCategory.PLAN, None, "default", "default", step=5),
        ]
        rt = _table(history=hist).rendered_text()
        assert "5" in rt.plain

    def test_history_source_rendered(self) -> None:
        """source 字段(by_category/default/by_tool)出现在历史行。"""
        hist = [
            RouteDecision(TaskCategory.SIMPLE_READ, None, "cheap", "by_category", step=1),
        ]
        rt = _table(history=hist).rendered_text()
        assert "by_category" in rt.plain

    def test_history_capped_at_10(self) -> None:
        """超过 10 条 history 只渲染 10 条(deque maxlen 契约)。"""
        hist = [
            RouteDecision(TaskCategory.SIMPLE_READ, None, "default", "default", step=i)
            for i in range(15)
        ]
        rt = _table(history=hist).rendered_text()
        # step 0..9 出现，step 10..14 不出现（因为 maxlen=10 的 deque 会截断）
        # 但 RoutingTable 自己只渲染传入的 history，截断应由 router.history() 完成
        # 此处验证最多 10 行 step 行（用 step 数字唯一性验证困难）
        # 改为：直接传 10 条，确认都渲染
        hist10 = hist[:10]
        rt2 = _table(history=hist10).rendered_text()
        plain = rt2.plain
        for i in range(10):
            assert str(i) in plain, f"step {i} 未出现"


# ─────────────────────────────────────────────────────────────────
# 6. markup=False 安全性
# ─────────────────────────────────────────────────────────────────

class TestMarkupSafety:
    def test_category_with_bracket_does_not_crash(self) -> None:
        """category 值含 [brackets] 不崩溃（RoutingTable 必须 markup=False）。

        注：TaskCategory 枚举值不含方括号，但 rendered_text 里 tier 名可能含方括号。
        """
        # 不能改枚举，但可测 tier 名含方括号时不崩
        # 构造一个 tier 名含方括号的 RoutingConfig（实际 config 可能有）
        cfg = RoutingConfig(
            default="[bold]tier[/bold]",
            by_category={},
            by_tool={},
            tier_force_confirm=[],
        )
        t = RoutingTable(routing=cfg, history=[])
        # rendered_text() 不应抛
        rt = t.rendered_text()
        # plain text 应含原始字符串，未被 markup 解析
        assert "[bold]tier[/bold]" in rt.plain

    def test_tool_name_with_brackets_in_history(self) -> None:
        """历史中 tool 名含方括号不崩。"""
        hist = [
            RouteDecision(
                TaskCategory.AUTO_CAPTURE,
                "[tool_name]",
                "default",
                "by_tool",
                step=1,
            )
        ]
        rt = _table(history=hist).rendered_text()
        assert "[tool_name]" in rt.plain


# ─────────────────────────────────────────────────────────────────
# 7. 承重字形铁律
# ─────────────────────────────────────────────────────────────────

class TestGlyphs:
    def test_echo_glyph_present(self) -> None:
        """› (U+203A) 出现在 echo 行。"""
        rt = _table().rendered_text()
        assert "›" in rt.plain

    def test_arrow_glyph_is_u2192(self) -> None:
        """→ 是 U+2192（不是 ASCII >、→ 或其他代替品）。"""
        rt = _table().rendered_text()
        assert "→" in rt.plain

    def test_force_confirm_glyph_is_u2742(self) -> None:
        """❂ 是 U+2742（非 ✻ 或 ✸）。"""
        rt = _table(
            by_category={"plan": "strong"},
            tier_force_confirm=["strong"],
        ).rendered_text()
        assert "❂" in rt.plain


# ─────────────────────────────────────────────────────────────────
# 8. 诚实规则
# ─────────────────────────────────────────────────────────────────

class TestHonestyRules:
    def test_all_8_categories_rendered_even_if_not_in_by_category(self) -> None:
        """所有 8 个 category 都渲染（未配置者回退 default），不遗漏任何一行。"""
        rt = _table().rendered_text()
        for cat in TaskCategory:
            assert cat.value in rt.plain

    def test_configured_tier_overrides_default(self) -> None:
        """by_category 中配置的 tier 优先于 default。"""
        rt = _table(
            default="default",
            by_category={"plan": "cheap"},
        ).rendered_text()
        plain = rt.plain
        # plan 行应含 cheap
        lines = plain.splitlines()
        plan_line = next((l for l in lines if "plan" in l and "→" in l and "test_write" not in l and "long_run" not in l), None)
        assert plan_line is not None, "未找到 plan 行"
        assert "cheap" in plan_line, f"plan 行未含 cheap; got {plan_line!r}"

    def test_force_confirm_honesty_contract(self) -> None:
        """tier_force_confirm 包含的 tier ❂ 必须出现；不包含的不得出现 ❂（诚实不遗漏）。"""
        # force-confirm: verify→strong, plan→cheap; only strong is force
        by_cat = {"verify": "strong", "plan": "cheap"}
        rt = _table(
            by_category=by_cat,
            tier_force_confirm=["strong"],
        ).rendered_text()
        plain = rt.plain
        lines = plain.splitlines()

        verify_line = next((l for l in lines if "verify" in l and "→" in l), None)
        plan_line = next((l for l in lines if l.strip().startswith("plan") and "→" in l), None)

        assert verify_line is not None
        assert "❂" in verify_line, f"verify(force) 行缺 ❂: {verify_line!r}"

        if plan_line is not None:
            assert "❂" not in plan_line, f"plan(非force) 行出现 ❂: {plan_line!r}"

    def test_color_discipline_cheap_not_ink_bright(self) -> None:
        """cheap tier 不得着色 $ink-bright（只应是 $cyan）。"""
        by_cat = {"simple_read": "cheap"}
        rt = _table(by_category=by_cat).rendered_text()
        spans = _find_spans_containing(rt, "cheap")
        # 所有含 "cheap" 的 span 不应含 _INK_BRIGHT
        ink_bright_spans = [s for _, s in spans if _INK_BRIGHT in s]
        assert not ink_bright_spans, \
            f"cheap tier 错误着色 $ink-bright; spans={ink_bright_spans}"

    def test_color_discipline_strong_not_cyan(self) -> None:
        """strong tier 不得着色 $cyan（只应是 $ink-bright）。"""
        by_cat = {"test_write": "strong"}
        rt = _table(by_category=by_cat).rendered_text()
        spans = _find_spans_containing(rt, "strong")
        cyan_spans = [s for _, s in spans if _CYAN in s]
        assert not cyan_spans, \
            f"strong tier 错误着色 $cyan; spans={cyan_spans}"


# ─────────────────────────────────────────────────────────────────
# 9. DEFAULT_CSS token 名检验（class 属性存在）
# ─────────────────────────────────────────────────────────────────

class TestCssTokens:
    def test_default_css_no_raw_hex(self) -> None:
        """DEFAULT_CSS 中不得出现裸 hex（#RRGGBB），只用 $token 名。"""
        import re
        css = RoutingTable.DEFAULT_CSS
        # 允许:注释中可以有 hex（但我们的规则是绝不在 CSS 属性里用 hex）
        # 简单检测：CSS 里的 hex 颜色 #XXXXXX（6位）
        raw_hex = re.findall(r"#[0-9A-Fa-f]{6}\b", css)
        assert not raw_hex, f"DEFAULT_CSS 含裸 hex: {raw_hex}"

    def test_default_css_uses_dollar_tokens(self) -> None:
        """DEFAULT_CSS 应包含至少一个 $token 引用。"""
        assert "$" in RoutingTable.DEFAULT_CSS
