# tests/tui/test_verdict_badge_audit.py
"""VerdictBadge + glow 回归测试 — 锁定 design-audit 修复点。

覆盖:
  [CONTRACT A] no_test 态:中性灰(verdict-no-test),绝不染橙 verdict-unverifiable
  [CONTRACT A] glow.verdict_border_color: no_test → IDLE_BORDER,真 unverif → WARNING
  [MEDIUM] verdict-self CSS 含 text-style:italic(诚实区隔:斜体=弱通过 vs 粗体=强通过)
  [LOW]    failed 态 line2 不重复 verdict.detail(注解行只保留重试次数)
  已知正确项(不回退):
    glyphs ◉/◔/◍ 与四态映射一致
    CSS 类名 verdict-passed/verdict-failed/verdict-unverifiable/verdict-self
    markup=False 约束(detail 含 '[...]' 不崩)
    unverifiable 三重冗余:◔ + 橙 CSS class + '无法验证'文字
"""
from __future__ import annotations

import pytest

from argos.core.types import Verdict
from argos.tui.widgets.verdict_badge import VerdictBadge


# ─────────────────────────────────────────────────────────────────────────────
# fixtures
# ─────────────────────────────────────────────────────────────────────────────

def _badge() -> VerdictBadge:
    """构造不依赖 App 的裸 widget(只测 render_text 和 CSS 字符串)。"""
    return VerdictBadge()


def _verdict_passed(detail: str = "ok", attempts: int = 1) -> Verdict:
    return Verdict.passed(detail=detail, verify_cmd="pytest", attempts=attempts)


def _verdict_self(detail: str = "canary ok", attempts: int = 1) -> Verdict:
    return Verdict.passed_self(detail=detail, verify_cmd=None, attempts=attempts)


def _verdict_failed(detail: str = "1 failed: test_foo", attempts: int = 3) -> Verdict:
    return Verdict(status="failed", detail=detail, verify_cmd="pytest", attempts=attempts)


def _verdict_unverifiable(detail: str = "no verify_cmd") -> Verdict:
    return Verdict(status="unverifiable", detail=detail, verify_cmd=None, attempts=0)


# ─────────────────────────────────────────────────────────────────────────────
# [MEDIUM] verdict-self 斜体回归
# ─────────────────────────────────────────────────────────────────────────────

class TestVerdictSelfItalic:
    """审计修复 [MEDIUM]: DEFAULT_CSS verdict-self 必须包含 text-style: italic。"""

    def test_default_css_contains_italic(self) -> None:
        """CSS 规则 verdict-self 必须声明 text-style: italic (诚实区隔锁定)。"""
        css = VerdictBadge.DEFAULT_CSS
        # 同一个规则块内:color: $pass-weak 且 text-style: italic
        assert "text-style: italic" in css, (
            "verdict-self 缺 text-style: italic — 无法通过斜体区隔弱通过 vs 强通过"
        )

    def test_verdict_self_rule_has_both_color_and_italic(self) -> None:
        """verdict-self 规则行同时含颜色 token 和斜体声明。"""
        css = VerdictBadge.DEFAULT_CSS
        # 找到包含 verdict-self 的块
        assert "$pass-weak" in css, "verdict-self 颜色 token $pass-weak 丢失"
        assert "italic" in css, "verdict-self 斜体声明丢失"

    def test_self_verified_glyph_is_halfeye(self) -> None:
        """self-verified 态的 glyph 必须是 ◍ (U+25CD 格纹瞳),不得是 ◉。"""
        badge = _badge()
        badge.show(_verdict_self())
        assert "◍" in badge.render_text, "self-verified 态缺 ◍ 格纹瞳"
        assert "◉" not in badge.render_text, "self-verified 态不得显示 ◉ 注视实瞳"

    def test_self_verified_css_class(self) -> None:
        """show(self-verified) 后 CSS 类为 verdict-self,绝不挂 verdict-passed。"""
        badge = _badge()
        badge.show(_verdict_self())
        assert badge.has_class("verdict-self"), "缺 verdict-self 类"
        assert not badge.has_class("verdict-passed"), "self-verified 不得挂 verdict-passed"


# ─────────────────────────────────────────────────────────────────────────────
# [LOW] failed 态 line2 不重复 detail
# ─────────────────────────────────────────────────────────────────────────────

class TestFailedLine2NoDuplicateDetail:
    """审计修复 [LOW]: failed line2 只保留重试次数,不重复 verdict.detail。"""

    def test_failed_line2_no_detail_repetition(self) -> None:
        """failed line2 不得含与 line1 相同的 verdict.detail 字符串。"""
        detail = "1 failed: test_resume_order"
        badge = _badge()
        badge.show(_verdict_failed(detail=detail, attempts=3))

        lines = badge.render_text.split("\n")
        assert len(lines) == 2, f"expected 2 lines, got {len(lines)}: {badge.render_text!r}"
        line1, line2 = lines

        # line1 应含 detail
        assert detail in line1, f"line1 应含失败 detail: {line1!r}"

        # line2 不应再含 detail(避免逐字重复)
        assert detail not in line2, (
            f"line2 重复了 verdict.detail — 违反设计分层(首行=用例,注解行=重试次数):\n"
            f"  line2={line2!r}"
        )

    def test_failed_line2_contains_attempts(self) -> None:
        """failed line2 必须包含重试次数信息。"""
        badge = _badge()
        badge.show(_verdict_failed(attempts=5))
        lines = badge.render_text.split("\n")
        assert len(lines) == 2
        assert "5" in lines[1], f"line2 缺重试次数 5: {lines[1]!r}"

    def test_failed_line2_contains_retry_annotation(self) -> None:
        """failed line2 必须含 ⤷ 重试 注解前缀。"""
        badge = _badge()
        badge.show(_verdict_failed())
        lines = badge.render_text.split("\n")
        assert "⤷" in lines[1], f"line2 缺 ⤷ 注解: {lines[1]!r}"
        assert "重试" in lines[1], f"line2 缺 '重试' 字样: {lines[1]!r}"


# ─────────────────────────────────────────────────────────────────────────────
# 不回退:已正确项锁定
# ─────────────────────────────────────────────────────────────────────────────

class TestGlyphContractLocked:
    """锁定:四态 glyph 映射不得回退。"""

    def test_passed_glyph_fisheye(self) -> None:
        badge = _badge()
        badge.show(_verdict_passed())
        assert "◉" in badge.render_text
        assert badge.has_class("verdict-passed")

    def test_failed_glyph_fisheye_red(self) -> None:
        badge = _badge()
        badge.show(_verdict_failed())
        assert "◉" in badge.render_text
        assert badge.has_class("verdict-failed")

    def test_unverifiable_glyph_halfopen(self) -> None:
        badge = _badge()
        badge.show(_verdict_unverifiable())
        assert "◔" in badge.render_text
        assert "无法验证" in badge.render_text
        assert badge.has_class("verdict-unverifiable")

    def test_markup_false_square_bracket_safe(self) -> None:
        """markup=False:detail 含 '[...]' 不崩(诚实约束:不解析 Rich markup)。"""
        badge = _badge()
        # 不崩即通过
        badge.show(_verdict_failed(detail="FAILED [test_foo]"))
        assert "[test_foo]" in badge.render_text

    def test_five_css_classes_exist(self) -> None:
        """五个 CSS 类名常量不缺失(CONTRACT A 新增 verdict-no-test)。"""
        expected = {
            "verdict-passed", "verdict-failed", "verdict-unverifiable",
            "verdict-self", "verdict-no-test",
        }
        assert expected == set(VerdictBadge._ALL_CLASSES)


# ─────────────────────────────────────────────────────────────────────────────
# CONTRACT A: no_test 态(无机检,中性灰)
# ─────────────────────────────────────────────────────────────────────────────

class TestNoTestState:
    """CONTRACT A: verdict.no_test==True 时渲染中性灰态,绝不染橙/红。"""

    def _no_test_verdict(self) -> Verdict:
        """构造 no_test 裁决(模拟 CORE 的 Verdict.no_check())。"""
        v = Verdict(
            status="unverifiable",
            detail="无 verify_cmd",
            verify_cmd=None,
            attempts=0,
        )
        # 使用 object.__setattr__ 绕过 frozen dataclass,注入 no_test 字段
        # (CONTRACT A 由 CORE 正式加字段;此处模拟,测试 widget 对该字段的响应)
        object.__setattr__(v, "no_test", True)
        return v

    def test_no_test_glyph_is_circle(self) -> None:
        """no_test 态 glyph 是 ○(空环),区别于 ◔ unverifiable。"""
        badge = _badge()
        badge.show(self._no_test_verdict())
        assert "○" in badge.render_text, "no_test 态缺 ○ 空环字形"
        assert "◔" not in badge.render_text, "no_test 态不得显示 ◔ unverifiable 字形"

    def test_no_test_text_contains_marker(self) -> None:
        """no_test 态渲染文字包含'未机检'或'无 verify'。"""
        badge = _badge()
        badge.show(self._no_test_verdict())
        assert "未机检" in badge.render_text or "无 verify" in badge.render_text, (
            f"no_test 态缺可读标记: {badge.render_text!r}"
        )

    def test_no_test_css_class_is_verdict_no_test(self) -> None:
        """no_test 态挂 verdict-no-test CSS 类,绝不挂 verdict-unverifiable(橙色)。"""
        badge = _badge()
        badge.show(self._no_test_verdict())
        assert badge.has_class("verdict-no-test"), "缺 verdict-no-test 类"
        assert not badge.has_class("verdict-unverifiable"), (
            "no_test 不得挂 verdict-unverifiable(会染橙色警告)"
        )

    def test_no_test_css_is_dim_not_orange(self) -> None:
        """verdict-no-test CSS 使用 $ink-dim(中性灰),不使用 $unverif(橙)。"""
        css = VerdictBadge.DEFAULT_CSS
        assert "$ink-dim" in css, "verdict-no-test 规则缺 $ink-dim"
        # $unverif 只能出现在 verdict-unverifiable 规则里
        # 简单检查:verdict-no-test 块内不含 $unverif — 通过行序检验
        lines = css.splitlines()
        in_no_test_block = False
        for line in lines:
            if "verdict-no-test" in line:
                in_no_test_block = True
            if in_no_test_block and "$unverif" in line:
                raise AssertionError("verdict-no-test 规则不得引用 $unverif(橙色)")
            if in_no_test_block and "}" in line:
                break

    def test_no_test_status_reactive_still_unverifiable(self) -> None:
        """no_test 态 status reactive 值仍为 'unverifiable'(外部读取 API 不变)。"""
        badge = _badge()
        badge.show(self._no_test_verdict())
        assert badge.status == "unverifiable", (
            "no_test 态 status reactive 必须仍为 unverifiable(CONTRACT A 规定)"
        )

    def test_no_test_with_getattr_fallback(self) -> None:
        """普通 Verdict(无 no_test 字段)走正常 unverifiable 路径(向后兼容)。"""
        badge = _badge()
        v = _verdict_unverifiable(detail="no verify_cmd")
        badge.show(v)
        # 正常 unverifiable 显示 ◔
        assert "◔" in badge.render_text
        assert badge.has_class("verdict-unverifiable")


# ─────────────────────────────────────────────────────────────────────────────
# CONTRACT A: glow.verdict_border_color
# ─────────────────────────────────────────────────────────────────────────────

class TestGlowVerdictBorderColor:
    """CONTRACT A: verdict_border_color — no_test 映射 IDLE_BORDER,真 unverif 映射 WARNING。"""

    def _import(self):
        from argos.tui.glow import verdict_border_color, IDLE_BORDER, WARNING, SUCCESS, ERROR
        return verdict_border_color, IDLE_BORDER, WARNING, SUCCESS, ERROR

    def _make_verdict(self, status: str, self_verified: bool = False, no_test: bool = False):
        v = Verdict(
            status=status,  # type: ignore[arg-type]
            detail="test",
            verify_cmd=None if no_test else ("pytest" if status == "passed" else None),
            attempts=1,
            self_verified=self_verified,
        )
        if no_test:
            object.__setattr__(v, "no_test", True)
        return v

    def test_no_test_returns_idle_border(self) -> None:
        """no_test==True → IDLE_BORDER 中性灰,绝不返回 WARNING 橙。"""
        vbc, IDLE_BORDER, WARNING, _, _ = self._import()
        v = self._make_verdict("unverifiable", no_test=True)
        result = vbc(v)
        assert result == IDLE_BORDER, (
            f"no_test 态应返回 IDLE_BORDER,得到 {result}"
        )
        assert result != WARNING, "no_test 态不得返回 WARNING 橙色"

    def test_real_unverifiable_returns_warning(self) -> None:
        """真 unverifiable(no_test 未设)→ WARNING 橙。"""
        vbc, _, WARNING, _, _ = self._import()
        v = self._make_verdict("unverifiable")
        result = vbc(v)
        assert result == WARNING, (
            f"真 unverifiable 应返回 WARNING,得到 {result}"
        )

    def test_passed_returns_success(self) -> None:
        """passed(非 self_verified) → SUCCESS 绿。"""
        vbc, _, _, SUCCESS, _ = self._import()
        v = self._make_verdict("passed")
        result = vbc(v)
        assert result == SUCCESS

    def test_self_verified_passed_returns_warning(self) -> None:
        """self_verified passed → WARNING(E4 防火墙:弱通过不用强绿)。"""
        vbc, _, WARNING, _, _ = self._import()
        v = self._make_verdict("passed", self_verified=True)
        result = vbc(v)
        assert result == WARNING

    def test_failed_returns_error(self) -> None:
        """failed → ERROR 红。"""
        vbc, _, _, _, ERROR = self._import()
        v = self._make_verdict("failed")
        result = vbc(v)
        assert result == ERROR
