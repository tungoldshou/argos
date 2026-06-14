# tests/tui/test_intent_card_choice.py
"""IntentCardChoice widget 验收测试(TDD · screen 09 Intent 确认环)。

覆盖范围:
  - 构造与继承断言(subclasses InlineChoice)
  - 字形铁律(◉ 标题、▸ 光标、◕ 自毁摘要)
  - 字段网格:goal 必渲、deliverable/constraints/not_doing 条件渲染
  - 风险药片色阶:低风险 $ink-dim 兜底 / 中风险 $unverif / 高危不可逆 $fail
  - 澄清问 '? ' 前缀、上限 3 条
  - 决策摘要精确文字三分支(confirm/edit/cancel)
  - 幂等(on_decide 只触发一次)
  - Fallback 路径(card_json 为空→渲 confirmation_text)
  - 诚实不变量:risk pill 不用 $eye / $pass / $pass-weak
  - 标签列 EAW 宽度对齐(4 显示宽度 + 2 空格 gutter)
"""
from __future__ import annotations

import dataclasses
from unittest.mock import MagicMock, patch

import pytest
from rich.text import Text

from argos.intent.card import IntentCard
from argos.tui.widgets.inline_choice import InlineChoice
from argos.tui.widgets.intent_card_choice import (
    IntentCardChoice,
    _HIGH_IRREVERSIBLE_FLAGS,
    _COL_EYE,
    _COL_FAIL,
    _COL_INK_BRIGHT,
    _COL_INK,
    _COL_INK_DIM,
    _COL_INK_FAINT,
    _COL_PLAN,
    _COL_UNVERIF,
    _field_row,
    _risk_pills,
)


# ── 共用 fixtures ──────────────────────────────────────────────────────────────

def _make_card(**overrides) -> IntentCard:
    """工厂:构造最小可用 IntentCard。"""
    base = dict(
        utterance="帮我写一个 hello.py",
        goal="创建 hello.py 输出 Hello, World!",
        deliverable="",
        constraints=(),
        not_doing=(),
        risk_flags=(),
        confirmation_required=True,
        questions=(),
    )
    base.update(overrides)
    return IntentCard(**base)


def _make_card_json(**overrides) -> dict:
    return dataclasses.asdict(_make_card(**overrides))


def _noop_decide(value: str, feedback: str) -> None:
    pass


def _make_widget(**kwargs) -> IntentCardChoice:
    """最小构造 IntentCardChoice(不挂载 App)。"""
    defaults = dict(
        card_json=_make_card_json(),
        confirmation_text="请确认:创建 hello.py",
        risk_flags=(),
        on_decide=_noop_decide,
    )
    defaults.update(kwargs)
    return IntentCardChoice(**defaults)


# ── 1. 继承 ────────────────────────────────────────────────────────────────────

class TestInheritance:
    def test_is_inline_choice_subclass(self):
        """IntentCardChoice 必须继承 InlineChoice。"""
        assert issubclass(IntentCardChoice, InlineChoice)

    def test_instantiates_without_app(self):
        """可在 App 外构造(不抛异常)。"""
        w = _make_widget()
        assert w is not None

    def test_escape_value_is_cancel(self):
        """escape_value 固定为 'cancel'(Esc 等价 option-3 取消,fail-closed)。"""
        w = _make_widget()
        assert w._escape_value == "cancel"

    def test_options_exactly_three(self):
        """固定三个选项:confirm / edit / cancel。"""
        w = _make_widget()
        values = [v for v, _ in w._options]
        assert values == ["confirm", "edit", "cancel"]

    def test_cursor_starts_at_zero(self):
        """光标初始指向 index=0(确认开始)。"""
        w = _make_widget()
        assert w._cursor == 0


# ── 2. CSS token 铁律 ─────────────────────────────────────────────────────────

class TestCssTokens:
    def test_default_css_has_eye_border(self):
        """DEFAULT_CSS border-left 必须是 $eye(金系),不能是 $unverif(橙系)。"""
        css = IntentCardChoice.DEFAULT_CSS
        assert "$eye" in css
        # 不能从父类的 $unverif 继承边框
        # 检查自己的 CSS 覆盖中含 border-left.*\$eye
        import re
        pattern = r"border-left\s*:\s*thick\s+\$eye"
        assert re.search(pattern, css), "DEFAULT_CSS 必须覆盖 border-left: thick $eye"

    def test_default_css_title_color_eye(self):
        """#ic-title color 必须是 $eye(金系意图卡,不是橙系审批卡)。"""
        css = IntentCardChoice.DEFAULT_CSS
        import re
        pattern = r"#ic-title\s*\{[^}]*color\s*:\s*\$eye"
        assert re.search(pattern, css), "#ic-title color 必须是 $eye"

    def test_no_hex_in_default_css(self):
        """DEFAULT_CSS 内不允许出现原生 hex 颜色(必须全用 $token)。"""
        import re
        hex_pattern = r"#[0-9A-Fa-f]{3,6}\b"
        matches = re.findall(hex_pattern, IntentCardChoice.DEFAULT_CSS)
        # 过滤掉 #ic-title / #ic-options 等 ID 选择器(以 - 或字母接续的不是 hex 色)
        actual_colors = [m for m in matches if not re.match(r"#[a-zA-Z]", m)]
        assert actual_colors == [], f"DEFAULT_CSS 含硬编码 hex: {actual_colors}"


# ── 3. 颜色常量同步检查 ────────────────────────────────────────────────────────

class TestColorConstants:
    """模块级 hex 常量必须和 theme.py 中的 token 值保持同步。"""

    def test_col_eye(self):
        assert _COL_EYE == "#D9A85C"     # $eye

    def test_col_fail(self):
        assert _COL_FAIL == "#F7768E"    # $fail

    def test_col_ink_bright(self):
        assert _COL_INK_BRIGHT == "#ECEEF5"   # $ink-bright

    def test_col_ink(self):
        assert _COL_INK == "#C8CCDA"    # $ink

    def test_col_ink_dim(self):
        assert _COL_INK_DIM == "#7E869C"   # $ink-dim

    def test_col_ink_faint(self):
        assert _COL_INK_FAINT == "#525A73"   # $ink-faint

    def test_col_plan(self):
        assert _COL_PLAN == "#7AA2F7"    # $plan

    def test_col_unverif(self):
        assert _COL_UNVERIF == "#FF9E64"   # $unverif


# ── 4. 字形铁律 ──────────────────────────────────────────────────────────────

class TestGlyphs:
    def test_title_text_exact(self):
        """标题文字必须精确匹配规范字符串。"""
        w = _make_widget()
        assert w._title == "◉ 意图确认 — 执行前回显"

    def test_title_glyph_is_fisheye(self):
        """标题首字符必须是 ◉(U+25C9 FISHEYE),不是 ◓/◔/◕/◍。"""
        w = _make_widget()
        assert w._title[0] == "◉"

    def test_options_text_cursor_glyph(self):
        """选项渲染:当前项前缀必须是 ▸(U+25B8)。"""
        w = _make_widget()
        rendered = w._options_text()
        plain = rendered.plain
        assert "▸" in plain   # ▸ BLACK RIGHT-POINTING SMALL TRIANGLE

    def test_summary_confirm_glyph(self):
        """confirm 决策摘要前缀必须是 ◕(U+25D5 阅毕眼)。"""
        w = _make_widget()
        summary = w._intent_summary("confirm")
        assert summary.startswith("◕")
        assert "◕" == summary[0]

    def test_summary_edit_glyph(self):
        w = _make_widget()
        summary = w._intent_summary("edit")
        assert summary.startswith("◕")

    def test_summary_cancel_glyph(self):
        w = _make_widget()
        summary = w._intent_summary("cancel")
        assert summary.startswith("◕")


# ── 5. 决策摘要精确文字 ───────────────────────────────────────────────────────

class TestDecisionSummary:
    def test_confirm_summary_exact(self):
        w = _make_widget()
        assert w._intent_summary("confirm") == "◕ 意图确认 → 已确认 · 转为 run"

    def test_edit_summary_exact(self):
        w = _make_widget()
        assert w._intent_summary("edit") == "◕ 意图确认 → 修改目标 · 已取回到输入"

    def test_cancel_summary_exact(self):
        w = _make_widget()
        assert w._intent_summary("cancel") == "◕ 意图确认 → 已取消 · 未执行任何动作"

    def test_unknown_value_falls_back(self):
        """未知 value 不崩溃,给一个合理兜底。"""
        w = _make_widget()
        summary = w._intent_summary("unknown_value")
        assert summary.startswith("◕")


# ── 6. 字段网格:_field_row() ─────────────────────────────────────────────────

class TestFieldRow:
    """_field_row(label, value, value_color) → Rich Text 行渲染。"""

    def test_returns_rich_text(self):
        row = _field_row("目标", "创建 hello.py", _COL_INK_BRIGHT)
        assert isinstance(row, Text)

    def test_label_in_output(self):
        row = _field_row("目标", "创建 hello.py", _COL_INK_BRIGHT)
        assert "目标" in row.plain

    def test_value_in_output(self):
        row = _field_row("目标", "创建 hello.py", _COL_INK_BRIGHT)
        assert "创建 hello.py" in row.plain

    def test_label_color_is_ink_faint(self):
        """标签列颜色必须是 $ink-faint。"""
        row = _field_row("目标", "v", _COL_INK_BRIGHT)
        # 找标签 span
        spans_with_faint = [
            s for s in row._spans
            if s.style and _COL_INK_FAINT.lower() in str(s.style).lower()
        ]
        assert spans_with_faint, f"label span with $ink-faint not found in: {row._spans}"

    def test_value_color_applied(self):
        """value 颜色必须用传入的 color 参数渲染。"""
        row = _field_row("目标", "v", _COL_INK_BRIGHT)
        spans_with_bright = [
            s for s in row._spans
            if s.style and _COL_INK_BRIGHT.lower() in str(s.style).lower()
        ]
        assert spans_with_bright

    def test_label_padded_to_display_width_4_plus_gutter(self):
        """标签 + gutter 总共至少 6 个打印列(EAW 4 + 2 空格 gutter)。"""
        row = _field_row("目标", "v", _COL_INK_BRIGHT)
        # plain 中标签部分 + gutter 必须在 value 之前占至少 6 列
        plain = row.plain
        # "目标" (2 CJK = 4 cols) + 2 spaces 至少
        idx_val = plain.index("v")
        prefix = plain[:idx_val]
        assert len(prefix) >= 4   # 至少 4 bytes(2 CJK + 2 spaces)


# ── 7. 风险药片:_risk_pills() ────────────────────────────────────────────────

class TestRiskPills:
    def test_no_flags_returns_dim_fallback_text(self):
        """无风险 flag → 返回 Text 含 '(无高危标记)' ,颜色 $ink-dim。"""
        result = _risk_pills(())
        assert isinstance(result, Text)
        assert "无高危标记" in result.plain

    def test_no_flags_color_is_ink_dim(self):
        """无 flag → 兜底文字颜色 $ink-dim。"""
        result = _risk_pills(())
        spans = [
            s for s in result._spans
            if s.style and _COL_INK_DIM.lower() in str(s.style).lower()
        ]
        assert spans, "无 flag 时兜底文字应为 $ink-dim"

    def test_normal_flag_color_is_unverif(self):
        """普通 flag(send_message) → chip 颜色 $unverif(橙)。"""
        result = _risk_pills(("send_message",))
        assert "send_message" in result.plain
        spans = [
            s for s in result._spans
            if s.style and _COL_UNVERIF.lower() in str(s.style).lower()
        ]
        assert spans, "普通 flag chip 应为 $unverif"

    def test_high_irreversible_flag_color_is_fail(self):
        """高危不可逆 flag(delete_files) → chip 颜色 $fail(红)。"""
        result = _risk_pills(("delete_files",))
        assert "delete_files" in result.plain
        spans = [
            s for s in result._spans
            if s.style and _COL_FAIL.lower() in str(s.style).lower()
        ]
        assert spans, "高危 flag chip 应为 $fail"

    def test_computer_action_flag_is_fail(self):
        """computer.* flag 永远是 $fail(不可逆,无论信任级别)。"""
        result = _risk_pills(("computer.click",))
        spans = [
            s for s in result._spans
            if s.style and _COL_FAIL.lower() in str(s.style).lower()
        ]
        assert spans, "computer.* flag chip 应为 $fail"

    def test_mixed_flags_renders_all(self):
        """混合 flag 全部出现在输出中。"""
        result = _risk_pills(("send_message", "delete_files"))
        assert "send_message" in result.plain
        assert "delete_files" in result.plain

    def test_no_gold_color_on_risk_pills(self):
        """风险 pill 绝不用 $eye 金色(铁律)。"""
        result = _risk_pills(("send_message",))
        spans_with_eye = [
            s for s in result._spans
            if s.style and _COL_EYE.lower() in str(s.style).lower()
        ]
        assert not spans_with_eye, "风险 pill 不得使用 $eye 金色"

    def test_no_green_color_on_risk_pills(self):
        """风险 pill 绝不用 $pass 绿色(铁律:pass-weak ≠ pass,且两者都不在此处)。"""
        _COL_PASS = "#9ECE6A"
        _COL_PASS_WEAK = "#73A857"
        result = _risk_pills(("send_message",))
        for col in (_COL_PASS, _COL_PASS_WEAK):
            spans_green = [
                s for s in result._spans
                if s.style and col.lower() in str(s.style).lower()
            ]
            assert not spans_green, f"风险 pill 不得使用绿色 {col}"


# ── 8. 高危不可逆 flag 集合 ─────────────────────────────────────────────────

class TestHighIrreversibleFlags:
    def test_delete_files_in_set(self):
        assert "delete_files" in _HIGH_IRREVERSIBLE_FLAGS

    def test_format_disk_in_set(self):
        assert "format_disk" in _HIGH_IRREVERSIBLE_FLAGS

    def test_financial_transfer_in_set(self):
        assert "financial_transfer" in _HIGH_IRREVERSIBLE_FLAGS

    def test_purchase_in_set(self):
        assert "purchase" in _HIGH_IRREVERSIBLE_FLAGS

    def test_uninstall_in_set(self):
        assert "uninstall" in _HIGH_IRREVERSIBLE_FLAGS

    def test_elevated_privilege_in_set(self):
        assert "elevated_privilege" in _HIGH_IRREVERSIBLE_FLAGS

    def test_computer_prefix_detected(self):
        """computer.* 前缀动态检测,不要求字面出现在集合内。"""
        # _risk_pills 测试已覆盖;此处确认 _HIGH_IRREVERSIBLE_FLAGS 或前缀逻辑存在
        from argos.tui.widgets.intent_card_choice import _is_high_irreversible
        assert _is_high_irreversible("computer.screenshot")
        assert _is_high_irreversible("computer.type_text")
        assert not _is_high_irreversible("send_message")


# ── 9. Widget 字段网格内容(通过 _build_field_rows() 公开接口) ───────────────

class TestFieldGridContent:
    def test_goal_always_present(self):
        """goal 字段必须在字段行中出现。"""
        w = _make_widget(card_json=_make_card_json(goal="创建 hello.py"))
        rows = w._build_field_rows()
        all_plain = " ".join(r.plain for r in rows)
        assert "创建 hello.py" in all_plain

    def test_deliverable_absent_when_empty(self):
        """deliverable 为空字符串时不渲染该行。"""
        w = _make_widget(card_json=_make_card_json(deliverable=""))
        rows = w._build_field_rows()
        all_plain = " ".join(r.plain for r in rows)
        assert "交付物" not in all_plain

    def test_deliverable_present_when_non_empty(self):
        w = _make_widget(card_json=_make_card_json(deliverable="一个 Python 脚本"))
        rows = w._build_field_rows()
        all_plain = " ".join(r.plain for r in rows)
        assert "交付物" in all_plain
        assert "一个 Python 脚本" in all_plain

    def test_constraints_joined_with_cjk_comma(self):
        """constraints tuple 用 、(U+3001) 拼接。"""
        w = _make_widget(card_json=_make_card_json(constraints=("A", "B")))
        rows = w._build_field_rows()
        all_plain = " ".join(r.plain for r in rows)
        assert "A、B" in all_plain   # 、= U+3001

    def test_not_doing_absent_when_empty(self):
        w = _make_widget(card_json=_make_card_json(not_doing=()))
        rows = w._build_field_rows()
        all_plain = " ".join(r.plain for r in rows)
        assert "不做" not in all_plain

    def test_not_doing_present_when_non_empty(self):
        w = _make_widget(card_json=_make_card_json(not_doing=("不修改生产库",)))
        rows = w._build_field_rows()
        all_plain = " ".join(r.plain for r in rows)
        assert "不做" in all_plain
        assert "不修改生产库" in all_plain

    def test_risk_row_always_present(self):
        """风险行始终存在(空时渲 '(无高危标记)')。"""
        w = _make_widget(card_json=_make_card_json(risk_flags=()))
        rows = w._build_field_rows()
        all_plain = " ".join(r.plain for r in rows)
        assert "风险" in all_plain
        assert "无高危标记" in all_plain

    def test_risk_row_with_flags(self):
        w = _make_widget(
            card_json=_make_card_json(risk_flags=("send_email",)),
            risk_flags=("send_email",),
        )
        rows = w._build_field_rows()
        all_plain = " ".join(r.plain for r in rows)
        assert "风险" in all_plain
        assert "send_email" in all_plain


# ── 10. 澄清问 ───────────────────────────────────────────────────────────────

class TestClarifyQuestions:
    def test_no_questions_empty(self):
        w = _make_widget(card_json=_make_card_json(questions=()))
        q_rows = w._build_question_rows()
        assert q_rows == []

    def test_question_prefix_is_question_mark(self):
        """每条澄清问前缀必须是 '? '(ASCII 问号 + 空格)。"""
        w = _make_widget(card_json=_make_card_json(questions=("同名时覆盖还是跳过?",)))
        q_rows = w._build_question_rows()
        assert len(q_rows) == 1
        assert isinstance(q_rows[0], Text)
        assert q_rows[0].plain.startswith("? ")

    def test_questions_capped_at_three(self):
        """超过 3 条时只取前 3 条(spec 上限)。"""
        w = _make_widget(card_json=_make_card_json(
            questions=("Q1", "Q2", "Q3", "Q4", "Q5")
        ))
        q_rows = w._build_question_rows()
        assert len(q_rows) == 3

    def test_question_color_is_plan(self):
        """澄清问颜色必须是 $plan 蓝色。"""
        w = _make_widget(card_json=_make_card_json(questions=("Q1?",)))
        q_rows = w._build_question_rows()
        row = q_rows[0]
        spans_plan = [
            s for s in row._spans
            if s.style and _COL_PLAN.lower() in str(s.style).lower()
        ]
        assert spans_plan, "澄清问颜色应为 $plan"

    def test_question_text_in_output(self):
        q_text = "同名 .md 已存在时覆盖还是跳过?"
        w = _make_widget(card_json=_make_card_json(questions=(q_text,)))
        q_rows = w._build_question_rows()
        assert q_text in q_rows[0].plain


# ── 11. 幂等 on_decide ────────────────────────────────────────────────────────

class TestIdempotent:
    def test_on_decide_called_only_once(self):
        """_finish 幂等:on_decide 最多调用一次。"""
        calls: list[tuple[str, str]] = []

        def decide(v: str, fb: str) -> None:
            calls.append((v, fb))

        w = _make_widget(on_decide=decide)
        # 连续调两次 _finish,on_decide 只被调一次
        w._finish("confirm", "")
        w._finish("confirm", "")
        assert len(calls) == 1


# ── 12. Fallback(card_json 空/损坏)─────────────────────────────────────────

class TestFallback:
    def test_empty_card_json_uses_confirmation_text(self):
        """card_json={} 时回退到 confirmation_text,不崩溃,不自动确认。"""
        w = IntentCardChoice(
            card_json={},
            confirmation_text="请确认:执行风险操作",
            risk_flags=(),
            on_decide=_noop_decide,
        )
        assert w is not None
        # 兜底文字被记录
        assert "请确认:执行风险操作" in w._fallback_text

    def test_bad_card_json_no_auto_confirm(self):
        """损坏的 card_json 不导致自动确认——escape_value 仍为 cancel。"""
        w = IntentCardChoice(
            card_json={"broken": True},
            confirmation_text="fallback",
            risk_flags=(),
            on_decide=_noop_decide,
        )
        assert w._escape_value == "cancel"

    def test_fallback_widget_has_options(self):
        """即使 card_json 损坏,三个选项仍存在。"""
        w = IntentCardChoice(
            card_json={},
            confirmation_text="fallback",
            risk_flags=(),
            on_decide=_noop_decide,
        )
        assert len(w._options) == 3

    def test_fallback_field_rows_contain_confirmation_text(self):
        """card_json={} → _build_field_rows() 返回含 confirmation_text 的行。"""
        w = IntentCardChoice(
            card_json={},
            confirmation_text="请确认备用文本",
            risk_flags=(),
            on_decide=_noop_decide,
        )
        rows = w._build_field_rows()
        assert len(rows) == 1
        assert "请确认备用文本" in rows[0].plain

    def test_fallback_question_rows_empty(self):
        """card_json={} → _build_question_rows() 返回空列表。"""
        w = IntentCardChoice(
            card_json={},
            confirmation_text="fallback",
            risk_flags=(),
            on_decide=_noop_decide,
        )
        q_rows = w._build_question_rows()
        assert q_rows == []

    def test_non_dict_card_json_falls_back(self):
        """card_json 不是 dict 时不崩溃。"""
        w = IntentCardChoice(
            card_json=None,  # type: ignore[arg-type]
            confirmation_text="非字典兜底",
            risk_flags=(),
            on_decide=_noop_decide,
        )
        rows = w._build_field_rows()
        assert "非字典兜底" in rows[0].plain


# ── 13. 提示行文字 ───────────────────────────────────────────────────────────

class TestHintText:
    def test_hint_contains_escape_cue(self):
        """提示行必须含 'Esc 取消'(fail-closed 关键提示)。"""
        w = _make_widget()
        hint = w._hint_text()
        assert "Esc" in hint
        assert "取消" in hint

    def test_hint_contains_navigation_cue(self):
        """提示行包含 ↑↓ 和 ↵。"""
        w = _make_widget()
        hint = w._hint_text()
        assert "↑↓" in hint
        assert "↵" in hint

    def test_hint_exact_primary_text(self):
        """一级提示精确文字。"""
        w = _make_widget()
        hint = w._hint_text()
        assert "↑↓ 选择 · ↵ 确认 · 数字直选 · Esc 取消" in hint


# ── 14. risk_flags 来源优先级 ────────────────────────────────────────────────

class TestRiskFlagsSource:
    def test_ev_risk_flags_used_when_card_json_has_none(self):
        """ev.risk_flags 传入时若 card_json 没有 risk_flags 键则使用 ev.risk_flags。"""
        card_json = _make_card_json(risk_flags=())
        # 删除 risk_flags 键,模拟"card_json 无此字段"场景
        card_json.pop("risk_flags", None)
        w = IntentCardChoice(
            card_json=card_json,
            confirmation_text="test",
            risk_flags=("send_sms",),
            on_decide=_noop_decide,
        )
        rows = w._build_field_rows()
        all_plain = " ".join(r.plain for r in rows)
        assert "send_sms" in all_plain

    def test_card_json_risk_flags_preferred(self):
        """card_json 有 risk_flags 时优先于 ev.risk_flags。"""
        card_json = _make_card_json(risk_flags=("delete_files",))
        w = IntentCardChoice(
            card_json=card_json,
            confirmation_text="test",
            risk_flags=("send_sms",),   # 应被 card_json 覆盖
            on_decide=_noop_decide,
        )
        rows = w._build_field_rows()
        all_plain = " ".join(r.plain for r in rows)
        assert "delete_files" in all_plain
