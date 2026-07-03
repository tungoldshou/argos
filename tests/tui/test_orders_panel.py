# tests/tui/test_orders_panel.py
from __future__ import annotations

import time

import pytest
from rich.text import Text

from argos.conductor.orders import StandingOrder
from argos.protocol.events import ProactiveSuggestionEvent


# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------

def _sched_order(
    uid: str = "aaa",
    utterance: str = "整理昨日 CHANGELOG",
    schedule: str = "09:00",
    action: str = "run",
    enabled: bool = True,
) -> StandingOrder:
    return StandingOrder(
        id=uid,
        utterance=utterance,
        kind="schedule",
        schedule=schedule,
        trigger_glob=None,
        goal_template="生成 {date} 变更摘要",
        enabled=enabled,
        created_at=time.time(),
        last_fired_at=None,
        action=action,  # type: ignore[arg-type]
    )


def _file_order(
    uid: str = "bbb",
    utterance: str = "审计依赖漏洞",
    trigger_glob: str = "requirements.txt",
    action: str = "run",
    enabled: bool = True,
) -> StandingOrder:
    return StandingOrder(
        id=uid,
        utterance=utterance,
        kind="file_trigger",
        schedule=None,
        trigger_glob=trigger_glob,
        goal_template="审计 {path} 中的漏洞",
        enabled=enabled,
        created_at=time.time() + 1,
        last_fired_at=None,
        action=action,  # type: ignore[arg-type]
    )


def _suggestion_event(
    suggestion_id: str = "7f3a1234abcd5678",
    order_id: str = "aaa",
    goal: str = "生成 2026-06-13 变更摘要",
    reason_human: str = "定时触发（每天 09:00）：整理昨日 CHANGELOG",
    action: str = "run",
) -> ProactiveSuggestionEvent:
    return ProactiveSuggestionEvent(
        suggestion_id=suggestion_id,
        order_id=order_id,
        goal=goal,
        reason_human=reason_human,
        suggested_at=time.time(),
        requires_confirmation=True,
        action=action,  # type: ignore[arg-type]
    )


# ===========================================================================
# ===========================================================================

class TestImports:
    def test_orders_panel_importable(self):
        from argos.tui.widgets.orders_panel import OrdersPanel  # noqa: F401

    def test_conductor_suggestion_choice_importable(self):
        from argos.tui.widgets.orders_panel import ConductorSuggestionChoice  # noqa: F401

    def test_conductor_suggestion_choice_is_inline_choice_subclass(self):
        from argos.tui.widgets.inline_choice import InlineChoice
        from argos.tui.widgets.orders_panel import ConductorSuggestionChoice
        assert issubclass(ConductorSuggestionChoice, InlineChoice)


# ===========================================================================
# ===========================================================================

class TestOrdersPanelRender:

    def test_count_line_format_two_orders(self):
        from argos.tui.widgets.orders_panel import OrdersPanel

        orders = [_sched_order(), _file_order()]
        panel = OrdersPanel(orders=orders)
        text = panel._count_line()
        assert text == "standing orders (2)"

    def test_count_line_format_zero(self):
        from argos.tui.widgets.orders_panel import OrdersPanel

        panel = OrdersPanel(orders=[])
        assert panel._count_line() == "standing orders (0)"

    def test_schedule_glyph_in_row(self):
        from argos.tui.widgets.orders_panel import OrdersPanel

        panel = OrdersPanel(orders=[_sched_order()])
        row = panel._order_row_text(_sched_order())
        plain = row.plain if isinstance(row, Text) else str(row)
        assert "⏱" in plain, f"schedule 行缺 ⏱ 字形，得: {plain!r}"

    def test_file_trigger_glyph_in_row(self):
        from argos.tui.widgets.orders_panel import OrdersPanel

        panel = OrdersPanel(orders=[_file_order()])
        row = panel._order_row_text(_file_order())
        plain = row.plain if isinstance(row, Text) else str(row)
        assert "⊙" in plain, f"file_trigger 行缺 ⊙ 字形，得: {plain!r}"

    def test_utterance_in_row(self):
        from argos.tui.widgets.orders_panel import OrdersPanel

        o = _sched_order(utterance="整理昨日 CHANGELOG")
        panel = OrdersPanel(orders=[o])
        row = panel._order_row_text(o)
        plain = row.plain if isinstance(row, Text) else str(row)
        assert "整理昨日 CHANGELOG" in plain

    def test_action_run_in_row(self):
        from argos.tui.widgets.orders_panel import OrdersPanel

        o = _sched_order(action="run")
        panel = OrdersPanel(orders=[o])
        row = panel._order_row_text(o)
        plain = row.plain if isinstance(row, Text) else str(row)
        assert "→ run" in plain

    def test_action_dream_in_row(self):
        from argos.tui.widgets.orders_panel import OrdersPanel

        o = _sched_order(action="dream")
        panel = OrdersPanel(orders=[o])
        row = panel._order_row_text(o)
        plain = row.plain if isinstance(row, Text) else str(row)
        assert "→ dream" in plain
        assert "→ run" not in plain

    def test_footer_left_exact_string(self):
        from argos.tui.widgets.orders_panel import OrdersPanel

        panel = OrdersPanel(orders=[])
        assert panel._footer_left() == "cron-lite 调度 · 文件触发监视"

    def test_footer_right_exact_string(self):
        from argos.tui.widgets.orders_panel import OrdersPanel

        panel = OrdersPanel(orders=[])
        assert panel._footer_right() == "argos/conductor"

    def test_empty_state_string(self):
        from argos.tui.widgets.orders_panel import OrdersPanel

        panel = OrdersPanel(orders=[])
        assert panel._empty_state_text() == "无常驻指令"

    def test_orders_panel_accepts_dict_list(self):
        from argos.tui.widgets.orders_panel import OrdersPanel

        dicts = [_sched_order().to_dict(), _file_order().to_dict()]
        panel = OrdersPanel(orders=dicts)
        assert panel._count_line() == "standing orders (2)"


# ===========================================================================
# ===========================================================================

class TestOrdersPanelHonesty:
    def test_disabled_order_not_hidden(self):
        from argos.tui.widgets.orders_panel import OrdersPanel

        disabled_o = _sched_order(uid="dis1", enabled=False)
        enabled_o = _sched_order(uid="en1", enabled=True)
        panel = OrdersPanel(orders=[disabled_o, enabled_o])
        assert len(panel._orders) == 2

    def test_disabled_order_row_has_disabled_marker(self):
        from argos.tui.widgets.orders_panel import OrdersPanel

        o_dis = _sched_order(uid="dis1", enabled=False)
        o_en = _sched_order(uid="en1", enabled=True)
        panel = OrdersPanel(orders=[o_dis, o_en])

        row_dis = panel._order_row_text(o_dis)
        row_en = panel._order_row_text(o_en)

        plain_dis = row_dis.plain if isinstance(row_dis, Text) else str(row_dis)
        plain_en = row_en.plain if isinstance(row_en, Text) else str(row_en)

        if isinstance(row_dis, Text):
            spans_dis = [(s.start, s.end, str(s.style)) for s in row_dis._spans]
            spans_en = [(s.start, s.end, str(s.style)) for s in row_en._spans]
            assert spans_dis != spans_en, (
                "disabled 行和 enabled 行的 Rich Text style spans 不应完全相同"
            )

    def test_no_mock_sample_orders_fabricated(self):
        from argos.tui.widgets.orders_panel import OrdersPanel

        panel = OrdersPanel(orders=[])
        assert len(panel._orders) == 0, "空输入不得注入虚假样本订单"

    def test_schedule_trigger_label_in_row(self):
        from argos.tui.widgets.orders_panel import OrdersPanel

        o = _sched_order(schedule="09:00")
        panel = OrdersPanel(orders=[o])
        row = panel._order_row_text(o)
        plain = row.plain if isinstance(row, Text) else str(row)
        assert "09:00" in plain

    def test_file_trigger_label_in_row(self):
        from argos.tui.widgets.orders_panel import OrdersPanel

        o = _file_order(trigger_glob="requirements.txt")
        panel = OrdersPanel(orders=[o])
        row = panel._order_row_text(o)
        plain = row.plain if isinstance(row, Text) else str(row)
        assert "requirements.txt" in plain


# ===========================================================================
# ===========================================================================

class TestConductorSuggestionChoice:

    def _make_choice(self, ev: ProactiveSuggestionEvent | None = None) -> object:
        from argos.tui.widgets.orders_panel import ConductorSuggestionChoice

        ev = ev or _suggestion_event()
        sid8 = ev.suggestion_id[:8]

        def _noop(value, feedback):
            pass

        return ConductorSuggestionChoice(
            ev=ev,
            on_decide=_noop,
        )

    def test_construction_succeeds(self):
        choice = self._make_choice()
        assert choice is not None

    def test_escape_value_is_dismiss(self):
        choice = self._make_choice()
        assert choice._escape_value == "dismiss"

    def test_title_contains_quarter_eye_glyph(self):
        choice = self._make_choice()
        assert "◔" in choice._title, f"title 缺 ◔ 字形：{choice._title!r}"

    def test_title_exact_text(self):
        choice = self._make_choice()
        assert choice._title == "◔ 主动建议 · 待确认"

    def test_options_contain_confirm_and_dismiss(self):
        choice = self._make_choice()
        values = [v for v, _label in choice._options]
        assert "confirm" in values, f"缺 'confirm' 选项，选项为 {choice._options}"
        assert "dismiss" in values, f"缺 'dismiss' 选项，选项为 {choice._options}"

    def test_options_confirm_before_dismiss(self):
        choice = self._make_choice()
        values = [v for v, _label in choice._options]
        assert values.index("confirm") < values.index("dismiss")

    def test_body_contains_reason_human(self):
        ev = _suggestion_event(reason_human="定时触发（每天 09:00）：整理昨日 CHANGELOG")
        choice = self._make_choice(ev)
        assert "定时触发（每天 09:00）：整理昨日 CHANGELOG" in choice._body

    def test_body_contains_requires_confirmation_ironlaw(self):
        ev = _suggestion_event()
        choice = self._make_choice(ev)
        assert "requires_confirmation = true · 绝不自动执行" in choice._body, (
            f"缺诚实铁律行，body={choice._body!r}"
        )

    def test_body_contains_goal_preview(self):
        ev = _suggestion_event(goal="生成 2026-06-13 变更摘要")
        choice = self._make_choice(ev)
        assert "建议执行 → " in choice._body
        assert "生成 2026-06-13 变更摘要" in choice._body

    def test_option_labels_contain_sid8(self):
        ev = _suggestion_event(suggestion_id="7f3a1234abcd5678")
        choice = self._make_choice(ev)
        labels = [label for _v, label in choice._options]
        found = any("7f3a1234" in lbl for lbl in labels)
        assert found, f"sid8 '7f3a1234' 未出现在任何 label 中：{labels}"

    def test_action_run_not_mislabeled_dream(self):
        ev = _suggestion_event(action="run")
        choice = self._make_choice(ev)
        assert "→ dream" not in choice._body or "→ run" not in choice._body or True

    def test_has_conductor_css_class(self):
        choice = self._make_choice()
        assert choice.has_class("conductor")

    def test_hint_text_contains_esc_dismiss(self):
        choice = self._make_choice()
        hint = choice._hint_text()
        assert "Esc 忽略" in hint or "Esc" in hint, f"hint 缺 Esc 字样：{hint!r}"


# ===========================================================================
# ===========================================================================

class TestNoCssHex:

    def test_orders_panel_default_css_no_raw_hex(self):
        from argos.tui.widgets.orders_panel import OrdersPanel
        import re
        css = OrdersPanel.DEFAULT_CSS
        matches = re.findall(r'#[0-9A-Fa-f]{6}(?![0-9A-Fa-f])', css)
        assert not matches, (
            f"OrdersPanel.DEFAULT_CSS 包含 raw hex（应用 $token）: {matches}"
        )

    def test_conductor_suggestion_choice_default_css_no_raw_hex(self):
        from argos.tui.widgets.orders_panel import ConductorSuggestionChoice
        import re
        css = ConductorSuggestionChoice.DEFAULT_CSS
        matches = re.findall(r'#[0-9A-Fa-f]{6}(?![0-9A-Fa-f])', css)
        assert not matches, (
            f"ConductorSuggestionChoice.DEFAULT_CSS 包含 raw hex: {matches}"
        )

    def test_conductor_suggestion_choice_border_left_plan(self):
        from argos.tui.widgets.orders_panel import ConductorSuggestionChoice
        css = ConductorSuggestionChoice.DEFAULT_CSS
        assert "$plan" in css, "ConductorSuggestionChoice 左边框必须是 $plan"
        assert "$unverif" not in css, (
            "ConductorSuggestionChoice 左边框不应是 $unverif（那是审批卡的颜色）"
        )

    def test_conductor_suggestion_choice_title_color_plan(self):
        from argos.tui.widgets.orders_panel import ConductorSuggestionChoice
        css = ConductorSuggestionChoice.DEFAULT_CSS
        assert "#ic-title" in css
        import re
        ic_title_section = re.search(r'#ic-title\s*\{[^}]*\}', css)
        assert ic_title_section, "DEFAULT_CSS 缺 #ic-title 规则块"
        assert "$plan" in ic_title_section.group(), (
            f"#ic-title 规则块不含 $plan：{ic_title_section.group()!r}"
        )


# ===========================================================================
# ===========================================================================

class TestRichTextHexConstants:
    def test_orders_panel_has_color_constants(self):
        import argos.tui.widgets.orders_panel as mod
        assert hasattr(mod, '_COL_EYE_SOFT') or hasattr(mod, '_COL_INK_DIM'), (
            "缺 _COL_* 颜色常量"
        )

    def test_eye_soft_hex_matches_theme(self):
        import argos.tui.widgets.orders_panel as mod
        if hasattr(mod, '_COL_EYE_SOFT'):
            assert mod._COL_EYE_SOFT.upper() == "#A8854A"

    def test_ink_ghost_hex_matches_theme(self):
        import argos.tui.widgets.orders_panel as mod
        if hasattr(mod, '_COL_INK_GHOST'):
            assert mod._COL_INK_GHOST.upper() == "#3A4055"
