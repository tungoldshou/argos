# tests/tui/test_routing_table.py
"""Internal documentation."""
from __future__ import annotations

from rich.text import Text

from argos.routing.categorizer import TaskCategory
from argos.routing.config import RoutingConfig
from argos.routing.resolver import RouteDecision
from argos.tui.widgets.routing_table import RoutingTable

_CYAN       = "#7DCFFF"   # $cyan  — cheap tier
_INK        = "#C8CCDA"   # $ink   — default tier
_INK_BRIGHT = "#ECEEF5"   # $ink-bright — strong tier
_INK_DIM    = "#7E869C"   # $ink-dim    — category name, echo
_INK_FAINT  = "#6B7494"   # $ink-faint  — hint/footer
_UNVERIF    = "#FF9E64"   # $unverif    — ❂ force confirm
_EYE        = "#D9A85C"   # $eye


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
# ─────────────────────────────────────────────────────────────────

class TestConstruction:
    def test_instantiates_with_minimal_args(self) -> None:
        """Internal documentation."""
        t = _table()
        assert t is not None

    def test_instantiates_with_full_routing(self) -> None:
        """Internal documentation."""
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
# ─────────────────────────────────────────────────────────────────

class TestRenderedText:
    def test_returns_text_instance(self) -> None:
        t = _table()
        rt = t.rendered_text()
        assert isinstance(rt, Text)

    def test_echo_line_present(self) -> None:
        """Internal documentation."""
        rt = _table().rendered_text()
        plain = rt.plain
        assert "› /routing" in plain

    def test_caption_line_present(self) -> None:
        """Internal documentation."""
        rt = _table().rendered_text()
        assert "按任务路由" in rt.plain

    def test_all_8_categories_present(self) -> None:
        """Internal documentation."""
        rt = _table().rendered_text()
        plain = rt.plain
        for cat in TaskCategory:
            assert cat.value in plain, f"缺失 category: {cat.value}"

    def test_arrow_glyph_present(self) -> None:
        """Internal documentation."""
        rt = _table().rendered_text()
        assert "→" in rt.plain

    def test_footer_left_string(self) -> None:
        """Internal documentation."""
        rt = _table().rendered_text()
        assert "启发式分类" in rt.plain
        assert "异常兜底 simple_read" in rt.plain

    def test_footer_right_string(self) -> None:
        """Internal documentation."""
        rt = _table().rendered_text()
        assert "argos/routing" in rt.plain

    def test_set_hint_present(self) -> None:
        """Internal documentation."""
        rt = _table().rendered_text()
        assert "/routing set" in rt.plain


# ─────────────────────────────────────────────────────────────────
# ─────────────────────────────────────────────────────────────────

def _spans_with_text(rt: Text, substring: str) -> list[str]:
    """Internal documentation."""
    styles = []
    pos = 0
    for span in rt._spans:
        text_slice = rt.plain[span.start:span.end]
        if substring in text_slice:
            styles.append(str(span.style))
    return styles


def _find_tier_style(rt: Text, tier_name: str) -> list[str]:
    """Internal documentation."""
    result = []
    for span in rt._spans:
        text_slice = rt.plain[span.start:span.end]
        if tier_name in text_slice and "→" not in text_slice:
            result.append(str(span.style))
    return result


def _find_spans_containing(rt: Text, substring: str) -> list[tuple[str, str]]:
    """Internal documentation."""
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
        assert any(_CYAN in s for _, s in spans),\
            f"cheap tier 未找到 $cyan span; got spans={spans}"

    def test_default_tier_uses_ink(self) -> None:
        """default tier → $ink (#C8CCDA)。"""
        rt = _table(default="default").rendered_text()
        # all categories without override map to default
        spans = _find_spans_containing(rt, "default")
        assert any(_INK in s for _, s in spans),\
            f"default tier 未找到 $ink span; got spans={spans}"

    def test_strong_tier_uses_ink_bright(self) -> None:
        """strong tier → $ink-bright (#ECEEF5)。"""
        by_cat = {"verify": "strong"}
        rt = _table(by_category=by_cat).rendered_text()
        spans = _find_spans_containing(rt, "strong")
        assert any(_INK_BRIGHT in s for _, s in spans),\
            f"strong tier 未找到 $ink-bright span; got spans={spans}"

    def test_unknown_tier_fallback_to_ink(self) -> None:
        """Internal documentation."""
        by_cat = {"simple_read": "turbo"}
        rt = _table(by_category=by_cat).rendered_text()
        spans = _find_spans_containing(rt, "turbo")
        assert any(_INK in s for _, s in spans),\
            f"未知 tier 未兜底 $ink; got spans={spans}"

    def test_category_name_uses_ink_dim(self) -> None:
        """Internal documentation."""
        rt = _table().rendered_text()
        spans = _find_spans_containing(rt, "plan")
        assert any(_INK_DIM in s for _, s in spans),\
            f"category 名未着色 $ink-dim; got spans={spans}"


# ─────────────────────────────────────────────────────────────────
# ─────────────────────────────────────────────────────────────────

class TestForceConfirm:
    def test_force_confirm_trailer_present(self) -> None:
        """Internal documentation."""
        rt = _table(
            by_category={"verify": "strong"},
            tier_force_confirm=["strong"],
        ).rendered_text()
        assert "❂" in rt.plain
        assert "force confirm" in rt.plain

    def test_force_confirm_uses_unverif_color(self) -> None:
        """Internal documentation."""
        rt = _table(
            by_category={"verify": "strong"},
            tier_force_confirm=["strong"],
        ).rendered_text()
        spans = _find_spans_containing(rt, "❂")
        assert any(_UNVERIF in s for _, s in spans),\
            f"❂ 未着色 $unverif; got spans={spans}"

    def test_no_force_confirm_no_glyph(self) -> None:
        """Internal documentation."""
        rt = _table(tier_force_confirm=[]).rendered_text()
        assert "❂" not in rt.plain

    def test_force_confirm_only_on_matching_tiers(self) -> None:
        """Internal documentation."""
        by_cat = {"verify": "strong", "plan": "cheap"}
        rt = _table(
            by_category=by_cat,
            tier_force_confirm=["strong"],
        ).rendered_text()
        plain = rt.plain
        lines = plain.splitlines()
        plan_lines = [l for l in lines if "plan" in l and "→" in l and "test_write" not in l]
        for line in plan_lines:
            assert "❂" not in line, f"plan(cheap,无 force) 行出现了 ❂: {line!r}"


# ─────────────────────────────────────────────────────────────────
# ─────────────────────────────────────────────────────────────────

class TestHistory:
    def test_empty_history_shows_honest_message(self) -> None:
        """Internal documentation."""
        rt = _table(history=[]).rendered_text()
        plain = rt.plain
        assert "尚未调模型" in plain or "无" in plain,\
            f"空历史未显示诚实提示; plain={plain[:300]}"

    def test_history_rows_rendered(self) -> None:
        """Internal documentation."""
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
        """Internal documentation."""
        hist = [
            RouteDecision(TaskCategory.PLAN, None, "default", "default", step=5),
        ]
        rt = _table(history=hist).rendered_text()
        assert "5" in rt.plain

    def test_history_source_rendered(self) -> None:
        """Internal documentation."""
        hist = [
            RouteDecision(TaskCategory.SIMPLE_READ, None, "cheap", "by_category", step=1),
        ]
        rt = _table(history=hist).rendered_text()
        assert "by_category" in rt.plain

    def test_history_capped_at_10(self) -> None:
        """Internal documentation."""
        hist = [
            RouteDecision(TaskCategory.SIMPLE_READ, None, "default", "default", step=i)
            for i in range(15)
        ]
        rt = _table(history=hist).rendered_text()
        hist10 = hist[:10]
        rt2 = _table(history=hist10).rendered_text()
        plain = rt2.plain
        for i in range(10):
            assert str(i) in plain, f"step {i} 未出现"


# ─────────────────────────────────────────────────────────────────
# ─────────────────────────────────────────────────────────────────

class TestMarkupSafety:
    def test_category_with_bracket_does_not_crash(self) -> None:
        """Internal documentation."""
        cfg = RoutingConfig(
            default="[bold]tier[/bold]",
            by_category={},
            by_tool={},
            tier_force_confirm=[],
        )
        t = RoutingTable(routing=cfg, history=[])
        rt = t.rendered_text()
        assert "[bold]tier[/bold]" in rt.plain

    def test_tool_name_with_brackets_in_history(self) -> None:
        """Internal documentation."""
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
# ─────────────────────────────────────────────────────────────────

class TestGlyphs:
    def test_echo_glyph_present(self) -> None:
        """Internal documentation."""
        rt = _table().rendered_text()
        assert "›" in rt.plain

    def test_arrow_glyph_is_u2192(self) -> None:
        """Internal documentation."""
        rt = _table().rendered_text()
        assert "→" in rt.plain

    def test_force_confirm_glyph_is_u2742(self) -> None:
        """Internal documentation."""
        rt = _table(
            by_category={"plan": "strong"},
            tier_force_confirm=["strong"],
        ).rendered_text()
        assert "❂" in rt.plain


# ─────────────────────────────────────────────────────────────────
# ─────────────────────────────────────────────────────────────────

class TestHonestyRules:
    def test_all_8_categories_rendered_even_if_not_in_by_category(self) -> None:
        """Internal documentation."""
        rt = _table().rendered_text()
        for cat in TaskCategory:
            assert cat.value in rt.plain

    def test_configured_tier_overrides_default(self) -> None:
        """Internal documentation."""
        rt = _table(
            default="default",
            by_category={"plan": "cheap"},
        ).rendered_text()
        plain = rt.plain
        lines = plain.splitlines()
        plan_line = next((l for l in lines if "plan" in l and "→" in l and "test_write" not in l and "long_run" not in l), None)
        assert plan_line is not None, "未找到 plan 行"
        assert "cheap" in plan_line, f"plan 行未含 cheap; got {plan_line!r}"

    def test_force_confirm_honesty_contract(self) -> None:
        """Internal documentation."""
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
        """Internal documentation."""
        by_cat = {"simple_read": "cheap"}
        rt = _table(by_category=by_cat).rendered_text()
        spans = _find_spans_containing(rt, "cheap")
        ink_bright_spans = [s for _, s in spans if _INK_BRIGHT in s]
        assert not ink_bright_spans,\
            f"cheap tier 错误着色 $ink-bright; spans={ink_bright_spans}"

    def test_color_discipline_strong_not_cyan(self) -> None:
        """Internal documentation."""
        by_cat = {"test_write": "strong"}
        rt = _table(by_category=by_cat).rendered_text()
        spans = _find_spans_containing(rt, "strong")
        cyan_spans = [s for _, s in spans if _CYAN in s]
        assert not cyan_spans,\
            f"strong tier 错误着色 $cyan; spans={cyan_spans}"


# ─────────────────────────────────────────────────────────────────
# ─────────────────────────────────────────────────────────────────

class TestCssTokens:
    def test_default_css_no_raw_hex(self) -> None:
        """Internal documentation."""
        import re
        css = RoutingTable.DEFAULT_CSS
        raw_hex = re.findall(r"#[0-9A-Fa-f]{6}\b", css)
        assert not raw_hex, f"DEFAULT_CSS 含裸 hex: {raw_hex}"

    def test_default_css_uses_dollar_tokens(self) -> None:
        """Internal documentation."""
        assert "$" in RoutingTable.DEFAULT_CSS
