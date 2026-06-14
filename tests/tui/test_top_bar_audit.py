# tests/tui/test_top_bar_audit.py
"""TopBar 回归测试 — 锁定 2026-06-14 design-audit 修复点。

覆盖:
  [MEDIUM] blocked 阶段 ◓ 字形已映射(字形铁律 README §字形铁律 line 85)
  [MEDIUM] blocked 阶段眼色为 $unverif (#FF9E64),不得与 idle ◌ 混淆
  [MEDIUM] Trust 徽标:set_state(trust_level=N, trust_label=...) 在 badges() 末尾追加
  [MEDIUM] Trust L0–L3:_badge_style → $eye-soft (#A8854A)
  [MEDIUM] Trust L4:徽标前缀 '⏻ ',_badge_style → $fail (#F7768E)
  [LOW]    $well 背景 token 说明:DEFAULT_CSS 含 $surface(已通过注释记录等价性,无渲染漂移)

已知正确项(不回退):
  字形字典原有 6 个 phase 不变
  badges() 顺序:plan / YOLO / DEMO 脚本演示 / 未配 key / LIVE 位于 Trust 之前
  has_key=False 时绝不出现 LIVE
  markup=False(render() 用 Rich Text 不走 markup 解析)
"""
from __future__ import annotations

import pytest

from argos.tui.widgets.top_bar import (
    TopBar,
    _PHASE_GLYPH,
    _EYE_SOFT,
    _EYE,
    _UNVERIF,
    _FAIL,
    _PASS,
    _PLAN,
)


# ─────────────────────────────────────────────────────────────────────────────
# helpers
# ─────────────────────────────────────────────────────────────────────────────

def _bar(**kwargs) -> TopBar:
    """裸 TopBar,不挂 App(只测 badges() / render_text / _badge_style)。"""
    return TopBar(**kwargs)


# ─────────────────────────────────────────────────────────────────────────────
# [MEDIUM] blocked 字形映射 & 眼色
# ─────────────────────────────────────────────────────────────────────────────

class TestBlockedPhase:
    """审计修复 [MEDIUM]: blocked 阶段必须映射 ◓ 并染 $unverif 橙色。"""

    def test_blocked_glyph_in_dict(self) -> None:
        """_PHASE_GLYPH['blocked'] == '◓' (U+25D3)。"""
        assert "blocked" in _PHASE_GLYPH, "'blocked' key missing from _PHASE_GLYPH"
        assert _PHASE_GLYPH["blocked"] == "◓", (
            f"blocked glyph should be ◓, got {_PHASE_GLYPH['blocked']!r}"
        )

    def test_blocked_glyph_in_render(self) -> None:
        """set_phase('blocked') 后 render_text 含 ◓,不得含 ◌(idle glyph)。"""
        bar = _bar()
        bar.set_phase("blocked")
        text = bar.render_text
        assert "◓" in text, f"◓ not in render_text after set_phase('blocked'): {text!r}"
        assert "◌" not in text, (
            f"◌ (idle glyph) must not appear when phase=blocked: {text!r}"
        )

    def test_blocked_eye_color_is_unverif(self) -> None:
        """blocked 相眼色为 $unverif (#FF9E64),不得为 $eye-soft (#A8854A) 或 $eye (#D9A85C)。"""
        bar = _bar()
        bar.set_phase("blocked")
        rendered = bar.render()
        # Rich Text 内 '◓ ' span 的 style 必须含 _UNVERIF
        eye_span_style = rendered._spans[0].style if rendered._spans else ""
        assert _UNVERIF in str(eye_span_style), (
            f"blocked eye span style should contain {_UNVERIF}, got {eye_span_style!r}"
        )
        assert _EYE_SOFT not in str(eye_span_style), (
            f"blocked eye must not be $eye-soft {_EYE_SOFT}"
        )

    def test_idle_still_uses_eye_soft(self) -> None:
        """idle 相保持 $eye-soft(不被 blocked 修改逻辑影响)。"""
        bar = _bar()
        bar.set_phase("idle")
        rendered = bar.render()
        eye_span_style = rendered._spans[0].style if rendered._spans else ""
        assert _EYE_SOFT in str(eye_span_style), (
            f"idle eye should be $eye-soft {_EYE_SOFT}, got {eye_span_style!r}"
        )

    def test_act_phase_uses_eye(self) -> None:
        """act 相保持 $eye 亮金(对照组)。"""
        bar = _bar()
        bar.set_phase("act")
        rendered = bar.render()
        eye_span_style = rendered._spans[0].style if rendered._spans else ""
        assert _EYE in str(eye_span_style), (
            f"act eye should be $eye {_EYE}, got {eye_span_style!r}"
        )


# ─────────────────────────────────────────────────────────────────────────────
# [MEDIUM] Trust 徽标出现与顺序
# ─────────────────────────────────────────────────────────────────────────────

class TestTrustBadgePresence:
    """审计修复 [MEDIUM]: Trust 徽标在 badges() 末尾,内容正确。"""

    def test_no_trust_badge_by_default(self) -> None:
        """默认不设置 trust_level 时,badges() 不含任何 Trust 徽标(Ln 格式)。"""
        bar = _bar()
        bar.set_state(demo=False, has_key=True)
        bs = bar.badges()
        # Trust 徽标匹配模式:L后跟数字(0-4)或 '⏻ ' 前缀;排除 'LIVE'
        import re
        trust_badges = [b for b in bs if re.match(r"^(⏻ )?L\d", b)]
        assert trust_badges == [], f"unexpected trust badge(s) in default state: {trust_badges}"

    def test_trust_l1_badge_text(self) -> None:
        """trust_level=1, trust_label='只有危险操作才问' → 徽标文本 'L1 · 只有危险操作才问'。"""
        bar = _bar()
        bar.set_state(demo=False, has_key=True, trust_level=1, trust_label="只有危险操作才问")
        bs = bar.badges()
        assert "L1 · 只有危险操作才问" in bs, f"badges()={bs}"

    def test_trust_badge_is_last(self) -> None:
        """Trust 徽标排在所有其他徽标之后(README §188 顺序)。"""
        bar = _bar()
        bar.set_state(demo=False, has_key=True, plan_mode=True, trust_level=2, trust_label="foo")
        bs = bar.badges()
        assert bs[-1].startswith("L2"), f"Trust badge must be last: {bs}"

    def test_trust_badge_after_live(self) -> None:
        """LIVE 出现时 Trust 徽标仍排在 LIVE 之后。"""
        import re
        bar = _bar()
        bar.set_state(demo=False, has_key=True, trust_level=0, trust_label="全自动")
        bs = bar.badges()
        live_idx = next((i for i, b in enumerate(bs) if b == "LIVE"), None)
        trust_idx = next((i for i, b in enumerate(bs) if re.match(r"^(⏻ )?L\d", b)), None)
        assert live_idx is not None, f"LIVE missing from badges: {bs}"
        assert trust_idx is not None, f"Trust badge missing from badges: {bs}"
        assert trust_idx > live_idx, (
            f"Trust badge must come after LIVE: live_idx={live_idx}, trust_idx={trust_idx}, badges={bs}"
        )

    def test_trust_l4_prefix(self) -> None:
        """trust_level=4 → 徽标文本以 '⏻ L4' 开头(README §152 升 L4 顶栏亮红灯)。"""
        bar = _bar()
        bar.set_state(demo=False, has_key=True, trust_level=4, trust_label="每步都问")
        bs = bar.badges()
        trust_badge = next((b for b in bs if "L4" in b), None)
        assert trust_badge is not None, f"L4 trust badge missing: {bs}"
        assert trust_badge.startswith("⏻ "), (
            f"L4 badge must start with '⏻ ', got {trust_badge!r}"
        )

    def test_trust_without_label(self) -> None:
        """trust_level 无 trust_label 时,徽标文本为 'L{n}'(无 ' · ' 后缀)。"""
        bar = _bar()
        bar.set_state(demo=False, has_key=True, trust_level=3)
        bs = bar.badges()
        trust_badge = next((b for b in bs if "L3" in b), None)
        assert trust_badge is not None, f"L3 badge missing: {bs}"
        assert " · " not in trust_badge, (
            f"badge without label must not contain ' · ': {trust_badge!r}"
        )

    def test_trust_badge_in_render_text(self) -> None:
        """Trust 徽标文本出现在 render_text 快照里。"""
        bar = _bar()
        bar.set_state(demo=False, has_key=True, trust_level=2, trust_label="谨慎")
        text = bar.render_text
        assert "L2" in text, f"L2 not in render_text: {text!r}"
        assert "谨慎" in text, f"trust_label not in render_text: {text!r}"


# ─────────────────────────────────────────────────────────────────────────────
# [MEDIUM] Trust 徽标着色
# ─────────────────────────────────────────────────────────────────────────────

class TestTrustBadgeColor:
    """审计修复 [MEDIUM]: Trust 徽标颜色规则(L0–L3=$eye-soft / L4=$fail)。"""

    @pytest.mark.parametrize("level", [0, 1, 2, 3])
    def test_trust_l0_l3_style_is_eye_soft(self, level: int) -> None:
        """L0–L3 Trust 徽标 _badge_style → $eye-soft (#A8854A)。"""
        bar = _bar()
        bar.set_state(demo=False, has_key=True, trust_level=level, trust_label="test")
        bs = bar.badges()
        trust_badge = next(b for b in bs if f"L{level}" in b)
        style = bar._badge_style(trust_badge)
        assert style == _EYE_SOFT, (
            f"L{level} badge style should be $eye-soft {_EYE_SOFT!r}, got {style!r}"
        )

    def test_trust_l4_style_is_fail(self) -> None:
        """L4 Trust 徽标 _badge_style → $fail (#F7768E)。"""
        bar = _bar()
        bar.set_state(demo=False, has_key=True, trust_level=4, trust_label="每步都问")
        bs = bar.badges()
        trust_badge = next(b for b in bs if "L4" in b)
        style = bar._badge_style(trust_badge)
        assert style == _FAIL, (
            f"L4 badge style should be $fail {_FAIL!r}, got {style!r}"
        )

    def test_live_badge_style_unchanged(self) -> None:
        """Trust 徽标的加入不影响 LIVE → $pass (#9ECE6A) 着色。"""
        bar = _bar()
        bar.set_state(demo=False, has_key=True, trust_level=1)
        assert bar._badge_style("LIVE") == _PASS

    def test_yolo_badge_style_unchanged(self) -> None:
        """YOLO → $fail (#F7768E) 不被 Trust 相关修改影响。"""
        bar = _bar()
        assert bar._badge_style("YOLO") == _FAIL

    def test_plan_badge_style_unchanged(self) -> None:
        """plan → $plan (#7AA2F7) 不被 Trust 修改影响。"""
        bar = _bar()
        assert bar._badge_style("plan") == _PLAN


# ─────────────────────────────────────────────────────────────────────────────
# 不回退:已知正确的原始行为锁定
# ─────────────────────────────────────────────────────────────────────────────

class TestExistingContractLocked:
    """锁定:原有 6-phase 字形字典、badge 规则、契约6 不回退。"""

    @pytest.mark.parametrize("phase,glyph", [
        ("idle",   "◌"),
        ("plan",   "◔"),
        ("act",    "◉"),
        ("verify", "❂"),
        ("report", "◕"),
        ("done",   "◕"),
    ])
    def test_original_glyphs_intact(self, phase: str, glyph: str) -> None:
        """原有 6 个 phase 字形不得改变。"""
        assert _PHASE_GLYPH.get(phase) == glyph, (
            f"phase={phase!r} glyph changed: expected {glyph!r}, got {_PHASE_GLYPH.get(phase)!r}"
        )

    def test_has_key_false_no_live(self) -> None:
        """契约6:has_key=False 时 badges() 绝不含 'LIVE'。"""
        bar = _bar()
        bar.set_state(demo=False, has_key=False)
        assert "LIVE" not in bar.badges(), "LIVE must never appear when has_key=False"

    def test_demo_true_shows_demo_badge(self) -> None:
        """demo=True 时 badges() 含 'DEMO 脚本演示'。"""
        bar = _bar()
        bar.set_state(demo=True)
        assert "DEMO 脚本演示" in bar.badges()

    def test_no_key_no_demo_shows_no_key_badge(self) -> None:
        """demo=False, has_key=False → badges() 含 '未配 key'。"""
        bar = _bar()
        bar.set_state(demo=False, has_key=False)
        assert "未配 key" in bar.badges()

    def test_plan_mode_badge(self) -> None:
        """plan_mode=True → badges() 首元素为 'plan'。"""
        bar = _bar()
        bar.set_state(plan_mode=True)
        assert bar.badges()[0] == "plan"

    def test_yolo_badge(self) -> None:
        """yolo=True → badges() 含 'YOLO'。"""
        bar = _bar()
        bar.set_state(yolo=True)
        assert "YOLO" in bar.badges()

    def test_unknown_phase_falls_back_to_idle_glyph(self) -> None:
        """未知 phase 字形回退 ◌(空态),不崩。"""
        bar = _bar()
        bar.set_phase("totally_unknown")
        text = bar.render_text
        assert "◌" in text, f"unknown phase should fall back to ◌: {text!r}"

    def test_render_text_contains_brand(self) -> None:
        """render_text 含 'Argos'(品牌名不消失)。"""
        bar = _bar()
        assert "Argos" in bar.render_text

    def test_set_state_partial_update(self) -> None:
        """set_state() 局部更新不覆盖未指定字段。"""
        bar = _bar()
        bar.set_state(yolo=True)
        bar.set_state(plan_mode=True)
        assert "YOLO" in bar.badges(), "yolo should persist after partial set_state"
        assert "plan" in bar.badges(), "plan should appear after second set_state"


# ─────────────────────────────────────────────────────────────────────────────
# [LOW] $surface/$well token 说明
# ─────────────────────────────────────────────────────────────────────────────

class TestBackgroundToken:
    """审计修复 [LOW]: DEFAULT_CSS 含 $surface 槽位(颜色与 $well 等价,注释已标注)。"""

    def test_default_css_has_background_surface(self) -> None:
        """DEFAULT_CSS 保留 background: $surface(裸 App 可解析的 Textual 内置槽位)。"""
        assert "$surface" in TopBar.DEFAULT_CSS, (
            "DEFAULT_CSS must reference $surface (Textual slot = $well value)"
        )

    def test_default_css_has_well_comment(self) -> None:
        """DEFAULT_CSS 注释标明 $surface 即 $well 值(诚实文档)。"""
        assert "$well" in TopBar.DEFAULT_CSS, (
            "DEFAULT_CSS comment must mention $well to document the equivalence"
        )
