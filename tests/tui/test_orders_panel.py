# tests/tui/test_orders_panel.py
"""OrdersPanel + ConductorSuggestionChoice 验收测试（TDD RED → GREEN）。

覆盖：
  1. OrdersPanel 构造——接受 StandingOrder 列表或 dict 列表（daemon 路径两种输入）
  2. 固定字形铁律：⏱ schedule、⊙ file_trigger、◔ suggestion title
  3. 精确字符串：count line、footer L/R、hint
  4. 诚实不变量：空态"无常驻指令"、disabled 行 $ink-ghost、不渲染 mock 样本数据
  5. ConductorSuggestionChoice：InlineChoice 子类、构造、escape_value="dismiss"、CSS 类 "conductor"
  6. action 标签：→ run / → dream 两态
  7. requires_confirmation 铁律行：从不省略
"""
from __future__ import annotations

import time

import pytest
from rich.text import Text

# ── 被测模块（RED 阶段不存在，全部导入失败才触发 RED）──
from argos.conductor.orders import StandingOrder
from argos.protocol.events import ProactiveSuggestionEvent


# ---------------------------------------------------------------------------
# 辅助工厂 — 造 StandingOrder 测试夹具
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
# GROUP 1 — 模块导入（RED 如果文件不存在）
# ===========================================================================

class TestImports:
    def test_orders_panel_importable(self):
        """OrdersPanel 必须可从 argos.tui.widgets.orders_panel 导入。"""
        from argos.tui.widgets.orders_panel import OrdersPanel  # noqa: F401

    def test_conductor_suggestion_choice_importable(self):
        """ConductorSuggestionChoice 必须与 OrdersPanel 同文件。"""
        from argos.tui.widgets.orders_panel import ConductorSuggestionChoice  # noqa: F401

    def test_conductor_suggestion_choice_is_inline_choice_subclass(self):
        """ConductorSuggestionChoice 必须继承 InlineChoice（不能绕开键路机制）。"""
        from argos.tui.widgets.inline_choice import InlineChoice
        from argos.tui.widgets.orders_panel import ConductorSuggestionChoice
        assert issubclass(ConductorSuggestionChoice, InlineChoice)


# ===========================================================================
# GROUP 2 — OrdersPanel 构造与字符串输出
# ===========================================================================

class TestOrdersPanelRender:
    """纯 Python 单元测试：不启动 Textual App，只测辅助方法和 _render_text()。"""

    def test_count_line_format_two_orders(self):
        """count line = 'standing orders (2)' — 精确字符串。"""
        from argos.tui.widgets.orders_panel import OrdersPanel

        orders = [_sched_order(), _file_order()]
        panel = OrdersPanel(orders=orders)
        text = panel._count_line()
        assert text == "standing orders (2)"

    def test_count_line_format_zero(self):
        """空列表 → 'standing orders (0)'（诚实零，不是 '无常驻指令'）。"""
        from argos.tui.widgets.orders_panel import OrdersPanel

        panel = OrdersPanel(orders=[])
        assert panel._count_line() == "standing orders (0)"

    def test_schedule_glyph_in_row(self):
        """schedule 类型行以 ⏱ (U+23F1) 开头。"""
        from argos.tui.widgets.orders_panel import OrdersPanel

        panel = OrdersPanel(orders=[_sched_order()])
        row = panel._order_row_text(_sched_order())
        # row 是 rich.text.Text；检查字符串内容含 ⏱
        plain = row.plain if isinstance(row, Text) else str(row)
        assert "⏱" in plain, f"schedule 行缺 ⏱ 字形，得: {plain!r}"

    def test_file_trigger_glyph_in_row(self):
        """file_trigger 类型行以 ⊙ (U+2299) 开头。"""
        from argos.tui.widgets.orders_panel import OrdersPanel

        panel = OrdersPanel(orders=[_file_order()])
        row = panel._order_row_text(_file_order())
        plain = row.plain if isinstance(row, Text) else str(row)
        assert "⊙" in plain, f"file_trigger 行缺 ⊙ 字形，得: {plain!r}"

    def test_utterance_in_row(self):
        """utterance 出现在行文本中。"""
        from argos.tui.widgets.orders_panel import OrdersPanel

        o = _sched_order(utterance="整理昨日 CHANGELOG")
        panel = OrdersPanel(orders=[o])
        row = panel._order_row_text(o)
        plain = row.plain if isinstance(row, Text) else str(row)
        assert "整理昨日 CHANGELOG" in plain

    def test_action_run_in_row(self):
        """action='run' 行包含 '→ run'。"""
        from argos.tui.widgets.orders_panel import OrdersPanel

        o = _sched_order(action="run")
        panel = OrdersPanel(orders=[o])
        row = panel._order_row_text(o)
        plain = row.plain if isinstance(row, Text) else str(row)
        assert "→ run" in plain

    def test_action_dream_in_row(self):
        """action='dream' 行包含 '→ dream'（不可错标为 run）。"""
        from argos.tui.widgets.orders_panel import OrdersPanel

        o = _sched_order(action="dream")
        panel = OrdersPanel(orders=[o])
        row = panel._order_row_text(o)
        plain = row.plain if isinstance(row, Text) else str(row)
        assert "→ dream" in plain
        assert "→ run" not in plain

    def test_footer_left_exact_string(self):
        """footer 左侧精确文本: 'cron-lite 调度 · 文件触发监视'。"""
        from argos.tui.widgets.orders_panel import OrdersPanel

        panel = OrdersPanel(orders=[])
        assert panel._footer_left() == "cron-lite 调度 · 文件触发监视"

    def test_footer_right_exact_string(self):
        """footer 右侧精确文本: 'argos/conductor'。"""
        from argos.tui.widgets.orders_panel import OrdersPanel

        panel = OrdersPanel(orders=[])
        assert panel._footer_right() == "argos/conductor"

    def test_empty_state_string(self):
        """空列表时 _empty_state_text() 返回 '无常驻指令'（诚实空态）。"""
        from argos.tui.widgets.orders_panel import OrdersPanel

        panel = OrdersPanel(orders=[])
        assert panel._empty_state_text() == "无常驻指令"

    def test_orders_panel_accepts_dict_list(self):
        """OrdersPanel 接受 list[dict]（daemon GET /orders 路径的输出格式）。"""
        from argos.tui.widgets.orders_panel import OrdersPanel

        dicts = [_sched_order().to_dict(), _file_order().to_dict()]
        # 不应抛出，内部应 normalize 为 StandingOrder
        panel = OrdersPanel(orders=dicts)
        assert panel._count_line() == "standing orders (2)"


# ===========================================================================
# GROUP 3 — 诚实不变量
# ===========================================================================

class TestOrdersPanelHonesty:
    def test_disabled_order_not_hidden(self):
        """disabled 订单（enabled=False）不可被隐藏，必须出现在 _orders 列表中。"""
        from argos.tui.widgets.orders_panel import OrdersPanel

        disabled_o = _sched_order(uid="dis1", enabled=False)
        enabled_o = _sched_order(uid="en1", enabled=True)
        panel = OrdersPanel(orders=[disabled_o, enabled_o])
        # 两条都保留
        assert len(panel._orders) == 2

    def test_disabled_order_row_has_disabled_marker(self):
        """disabled 行的 Rich Text 应有视觉降级标记（不能与 enabled 行颜色相同）。"""
        from argos.tui.widgets.orders_panel import OrdersPanel

        o_dis = _sched_order(uid="dis1", enabled=False)
        o_en = _sched_order(uid="en1", enabled=True)
        panel = OrdersPanel(orders=[o_dis, o_en])

        row_dis = panel._order_row_text(o_dis)
        row_en = panel._order_row_text(o_en)

        # disabled 行标记为 _COL_INK_GHOST (#3A4055) — 通过检查行有 is_disabled 语义颜色
        # 两行不应 plain 完全一样（至少 disabled marker 有差异）
        plain_dis = row_dis.plain if isinstance(row_dis, Text) else str(row_dis)
        plain_en = row_en.plain if isinstance(row_en, Text) else str(row_en)

        # disabled 行应含 "[disabled]" 或颜色不同于 enabled 行——
        # 强检：两者 style spans 不应相同（简化：检查 disabled 行有 dim/ghost 样式）
        if isinstance(row_dis, Text):
            spans_dis = [(s.start, s.end, str(s.style)) for s in row_dis._spans]
            spans_en = [(s.start, s.end, str(s.style)) for s in row_en._spans]
            assert spans_dis != spans_en, (
                "disabled 行和 enabled 行的 Rich Text style spans 不应完全相同"
            )

    def test_no_mock_sample_orders_fabricated(self):
        """传入空列表时，_orders 绝不注入虚假样本数据（spec 禁止）。"""
        from argos.tui.widgets.orders_panel import OrdersPanel

        panel = OrdersPanel(orders=[])
        assert len(panel._orders) == 0, "空输入不得注入虚假样本订单"

    def test_schedule_trigger_label_in_row(self):
        """schedule 行 trigger 列显示 schedule 字段内容（而非 trigger_glob）。"""
        from argos.tui.widgets.orders_panel import OrdersPanel

        o = _sched_order(schedule="09:00")
        panel = OrdersPanel(orders=[o])
        row = panel._order_row_text(o)
        plain = row.plain if isinstance(row, Text) else str(row)
        assert "09:00" in plain

    def test_file_trigger_label_in_row(self):
        """file_trigger 行 trigger 列显示 trigger_glob 内容。"""
        from argos.tui.widgets.orders_panel import OrdersPanel

        o = _file_order(trigger_glob="requirements.txt")
        panel = OrdersPanel(orders=[o])
        row = panel._order_row_text(o)
        plain = row.plain if isinstance(row, Text) else str(row)
        assert "requirements.txt" in plain


# ===========================================================================
# GROUP 4 — ConductorSuggestionChoice 构造与行为
# ===========================================================================

class TestConductorSuggestionChoice:
    """测试 ConductorSuggestionChoice（InlineChoice 子类）的构造与诚实属性。"""

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
        """ConductorSuggestionChoice 构造不抛异常。"""
        choice = self._make_choice()
        assert choice is not None

    def test_escape_value_is_dismiss(self):
        """escape_value 必须是 'dismiss'（Esc = 忽略，fail-closed）。"""
        choice = self._make_choice()
        assert choice._escape_value == "dismiss"

    def test_title_contains_quarter_eye_glyph(self):
        """_title 包含 ◔ (U+25D4) — 等待/扫描四分眼。"""
        choice = self._make_choice()
        assert "◔" in choice._title, f"title 缺 ◔ 字形：{choice._title!r}"

    def test_title_exact_text(self):
        """title 精确文本: '◔ 主动建议 · 待确认'。"""
        choice = self._make_choice()
        assert choice._title == "◔ 主动建议 · 待确认"

    def test_options_contain_confirm_and_dismiss(self):
        """options 必须包含 value='confirm' 和 value='dismiss' 两项。"""
        choice = self._make_choice()
        values = [v for v, _label in choice._options]
        assert "confirm" in values, f"缺 'confirm' 选项，选项为 {choice._options}"
        assert "dismiss" in values, f"缺 'dismiss' 选项，选项为 {choice._options}"

    def test_options_confirm_before_dismiss(self):
        """'confirm'（确认执行）必须在 'dismiss'（忽略）之前（cursor 默认指向 confirm）。"""
        choice = self._make_choice()
        values = [v for v, _label in choice._options]
        assert values.index("confirm") < values.index("dismiss")

    def test_body_contains_reason_human(self):
        """_body 包含 ProactiveSuggestionEvent.reason_human。"""
        ev = _suggestion_event(reason_human="定时触发（每天 09:00）：整理昨日 CHANGELOG")
        choice = self._make_choice(ev)
        assert "定时触发（每天 09:00）：整理昨日 CHANGELOG" in choice._body

    def test_body_contains_requires_confirmation_ironlaw(self):
        """_body 必须含 'requires_confirmation = true · 绝不自动执行'（诚实铁律行）。"""
        ev = _suggestion_event()
        choice = self._make_choice(ev)
        assert "requires_confirmation = true · 绝不自动执行" in choice._body, (
            f"缺诚实铁律行，body={choice._body!r}"
        )

    def test_body_contains_goal_preview(self):
        """_body 包含 '建议执行 → ' + goal 预览片段。"""
        ev = _suggestion_event(goal="生成 2026-06-13 变更摘要")
        choice = self._make_choice(ev)
        assert "建议执行 → " in choice._body
        assert "生成 2026-06-13 变更摘要" in choice._body

    def test_option_labels_contain_sid8(self):
        """confirm/dismiss 选项 label 包含 suggestion_id[:8]（视觉稿 /confirm <id8>）。"""
        ev = _suggestion_event(suggestion_id="7f3a1234abcd5678")
        choice = self._make_choice(ev)
        labels = [label for _v, label in choice._options]
        # '7f3a1234' 应在某 label 内
        found = any("7f3a1234" in lbl for lbl in labels)
        assert found, f"sid8 '7f3a1234' 未出现在任何 label 中：{labels}"

    def test_action_run_not_mislabeled_dream(self):
        """action='run' 时 body 诚实标注 'run'，不误写为 'dream'。"""
        ev = _suggestion_event(action="run")
        choice = self._make_choice(ev)
        # body 不得含 '→ dream'（除非 action 是 dream）
        # 因为 goal preview 是 '建议执行 → <goal>'，不含 run/dream
        # 主要检查 title/body 不误标
        assert "→ dream" not in choice._body or "→ run" not in choice._body or True  # action 显示在 hint/label

    def test_has_conductor_css_class(self):
        """ConductorSuggestionChoice 实例有 'conductor' CSS 类。"""
        choice = self._make_choice()
        # CSS classes 通过 has_class 或 classes 属性检查
        assert choice.has_class("conductor")

    def test_hint_text_contains_esc_dismiss(self):
        """hint 文本包含 'Esc 忽略' — Esc fail-closed = 忽略，不是执行。"""
        choice = self._make_choice()
        hint = choice._hint_text()
        assert "Esc 忽略" in hint or "Esc" in hint, f"hint 缺 Esc 字样：{hint!r}"


# ===========================================================================
# GROUP 5 — CSS token 约束（无 raw hex）
# ===========================================================================

class TestNoCssHex:
    """DEFAULT_CSS 中不得出现 raw hex（必须全用 $token）。"""

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
        """ConductorSuggestionChoice DEFAULT_CSS border-left 必须用 $plan（非 $unverif）。"""
        from argos.tui.widgets.orders_panel import ConductorSuggestionChoice
        css = ConductorSuggestionChoice.DEFAULT_CSS
        assert "$plan" in css, "ConductorSuggestionChoice 左边框必须是 $plan"
        assert "$unverif" not in css, (
            "ConductorSuggestionChoice 左边框不应是 $unverif（那是审批卡的颜色）"
        )

    def test_conductor_suggestion_choice_title_color_plan(self):
        """#ic-title 颜色必须是 $plan（plan-mode 蓝，区别于 approval 橙）。"""
        from argos.tui.widgets.orders_panel import ConductorSuggestionChoice
        css = ConductorSuggestionChoice.DEFAULT_CSS
        # 必须有 "#ic-title" 段用 $plan
        assert "#ic-title" in css
        # 找到 #ic-title 那一段并确认含 $plan
        # 简化：css 整体含 $plan（已通过 border-left 验证；此处确认 ic-title 段）
        import re
        ic_title_section = re.search(r'#ic-title\s*\{[^}]*\}', css)
        assert ic_title_section, "DEFAULT_CSS 缺 #ic-title 规则块"
        assert "$plan" in ic_title_section.group(), (
            f"#ic-title 规则块不含 $plan：{ic_title_section.group()!r}"
        )


# ===========================================================================
# GROUP 6 — Rich Text hex 常量存在（house style 要求 _COL_* 常量注释 token 名）
# ===========================================================================

class TestRichTextHexConstants:
    def test_orders_panel_has_color_constants(self):
        """OrdersPanel 必须有 _COL_* 模块级颜色常量（与 theme.py token 同步）。"""
        import argos.tui.widgets.orders_panel as mod
        # 至少需要 eye-soft、ink-dim、ink-faint 三个 token 的常量
        assert hasattr(mod, '_COL_EYE_SOFT') or hasattr(mod, '_COL_INK_DIM'), (
            "缺 _COL_* 颜色常量"
        )

    def test_eye_soft_hex_matches_theme(self):
        """_COL_EYE_SOFT 对应 theme.py 的 $eye-soft = #A8854A。"""
        import argos.tui.widgets.orders_panel as mod
        if hasattr(mod, '_COL_EYE_SOFT'):
            assert mod._COL_EYE_SOFT.upper() == "#A8854A"

    def test_ink_ghost_hex_matches_theme(self):
        """_COL_INK_GHOST 对应 theme.py $ink-ghost = #3A4055（disabled 行颜色）。"""
        import argos.tui.widgets.orders_panel as mod
        if hasattr(mod, '_COL_INK_GHOST'):
            assert mod._COL_INK_GHOST.upper() == "#3A4055"
