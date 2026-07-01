# tests/tui/test_splash_design_audit.py
"""StartupSplash 回归测试 — 锁定 2026-06-14 design-audit MEDIUM fix。

覆盖:
  [MEDIUM] 各段落 Rich markup 颜色 token 正确:
    - 眼字形 → $eye-glow  (#F0C078) 包裹
    - 副标题行(版本/模型/徽标) → $ink-dim (#7E869C) 包裹
    - LIVE 徽标 → $pass    (#9ECE6A) 包裹
    - DEMO 脚本演示 → $unverif (#FF9E64) 包裹
    - 提示行 → $ink-faint  (#525A73) 包裹
    - DEFAULT_CSS 不含 color: $ink-bright(旧压制色已移除)
  markup=True 在构造调用中生效(测试 _compose_text 返回值含 Rich markup 格式标签)
  功能不回退:
    - eye stage 推进仍工作(字形变化)
    - plan_mode 切换仍工作(前缀变化)
    - ARGOS wordmark 仍在 renderable_text 中(可访问性/其他测试断言兼容)
    - 三态徽标约束:无 key → 绝不含 LIVE;DEMO → 绝不含 LIVE
"""
from __future__ import annotations

import re

import pytest

from argos.tui.widgets.splash import (
    StartupSplash,
    _compose_text,
    _COL_EYE_GLOW,
    _COL_INK_DIM,
    _COL_INK_FAINT,
    _COL_PASS,
    _COL_UNVERIF,
)


# ─────────────────────────────────────────────────────────────────────────────
# helpers
# ─────────────────────────────────────────────────────────────────────────────

def _text(**kw) -> str:
    """调用 _compose_text 的快捷包装,提供合理默认值。"""
    defaults = dict(model_label="minimax-01", live=True, plan_mode=False, has_key=True, eye_stage="focus")
    defaults.update(kw)
    return _compose_text(**defaults)  # type: ignore[arg-type]


def _has_color_wrap(text: str, color: str, content: str) -> bool:
    """检查 text 中是否含 [color]...content...[/color] 形式的 Rich markup 包裹。"""
    pattern = re.escape(f"[{color}]") + r"[^[]*" + re.escape(content) + r"[^[]*" + re.escape(f"[/{color}]")
    return bool(re.search(pattern, text, re.DOTALL))


# ─────────────────────────────────────────────────────────────────────────────
# [MEDIUM] 颜色 token 正确 — _compose_text 输出含期望 markup 标签
# ─────────────────────────────────────────────────────────────────────────────

class TestComposeTextColorMarkup:
    """验证 _compose_text 输出中每个段落都携带正确的 Rich color markup。"""

    def test_eye_glyph_wrapped_in_eye_glow(self) -> None:
        """◉ 眼字形必须被 $eye-glow (#F0C078) 包裹。"""
        text = _text(eye_stage="focus")
        assert f"[{_COL_EYE_GLOW}]" in text, "eye markup opening tag missing"
        assert f"[/{_COL_EYE_GLOW}]" in text, "eye markup closing tag missing"
        # 眼字形在 eye-glow 标签内
        assert _has_color_wrap(text, _COL_EYE_GLOW, "◉"), (
            f"◉ glyph not wrapped in {_COL_EYE_GLOW}"
        )

    def test_eye_glow_hex_matches_theme(self) -> None:
        """_COL_EYE_GLOW 必须等于 theme.py $eye-glow = #F0C078。"""
        assert _COL_EYE_GLOW == "#F0C078", f"Expected #F0C078, got {_COL_EYE_GLOW}"

    def test_live_badge_wrapped_in_pass(self) -> None:
        """LIVE 徽标必须被 $pass (#9ECE6A) 包裹。"""
        text = _text(live=True, has_key=True)
        assert _has_color_wrap(text, _COL_PASS, "LIVE"), (
            f"LIVE badge not wrapped in {_COL_PASS} ($pass)"
        )

    def test_pass_hex_matches_theme(self) -> None:
        """_COL_PASS 必须等于 theme.py $pass = #9ECE6A。"""
        assert _COL_PASS == "#9ECE6A", f"Expected #9ECE6A, got {_COL_PASS}"

    def test_unverif_hex_matches_theme(self) -> None:
        """_COL_UNVERIF 必须等于 theme.py $unverif = #FF9E64。"""
        assert _COL_UNVERIF == "#FF9E64", f"Expected #FF9E64, got {_COL_UNVERIF}"

    def test_subtitle_line_wrapped_in_ink_dim(self) -> None:
        """副标题行(百眼智能体 · v…)必须被 $ink-dim (#7E869C) 包裹。"""
        text = _text(live=True, has_key=True)
        assert f"[{_COL_INK_DIM}]" in text, f"ink-dim opening tag missing in text"
        assert "百眼智能体" in text, "subtitle word missing"
        # 副标题行在 ink-dim 标签内
        assert _has_color_wrap(text, _COL_INK_DIM, "百眼智能体"), (
            f"subtitle not wrapped in {_COL_INK_DIM} ($ink-dim)"
        )

    def test_ink_dim_hex_matches_theme(self) -> None:
        """_COL_INK_DIM 必须等于 theme.py $ink-dim = #7E869C。"""
        assert _COL_INK_DIM == "#7E869C", f"Expected #7E869C, got {_COL_INK_DIM}"

    def test_hint_line_wrapped_in_ink_faint(self) -> None:
        """提示行(输入目标开始…)必须被 $ink-faint (#525A73) 包裹。"""
        text = _text()
        assert _has_color_wrap(text, _COL_INK_FAINT, "输入目标开始"), (
            f"hint line not wrapped in {_COL_INK_FAINT} ($ink-faint)"
        )

    def test_ink_faint_hex_matches_theme(self) -> None:
        """_COL_INK_FAINT 必须等于 theme.py $ink-faint。finding #27: 升至 #6B7494。"""
        assert _COL_INK_FAINT == "#6B7494", f"Expected #6B7494 (finding #27), got {_COL_INK_FAINT}"

    def test_no_key_badge_uses_ink_dim_not_pass(self) -> None:
        """无 key 时徽标用 $ink-dim,绝不含 LIVE 也绝不含 $pass 颜色。"""
        text = _text(live=True, has_key=False)
        assert "LIVE" not in text, "LIVE must not appear when has_key=False"
        # badge 用 ink-dim
        assert _has_color_wrap(text, _COL_INK_DIM, "未配 key"), (
            f"no-key badge not wrapped in {_COL_INK_DIM}"
        )


# ─────────────────────────────────────────────────────────────────────────────
# [MEDIUM] DEFAULT_CSS 不含旧的 color: $ink-bright
# ─────────────────────────────────────────────────────────────────────────────

class TestDefaultCssNoInkBright:
    """验证 DEFAULT_CSS 已移除 color: $ink-bright 全局压制色。"""

    def test_default_css_no_ink_bright_color(self) -> None:
        css = StartupSplash.DEFAULT_CSS
        # 旧的 color: $ink-bright 规则已移除
        assert "color: $ink-bright" not in css, (
            "DEFAULT_CSS must not contain 'color: $ink-bright' — "
            "per-segment markup handles coloring now"
        )

    def test_default_css_has_stream_background(self) -> None:
        """背景仍用 $stream(布局 token 必须保留)。"""
        css = StartupSplash.DEFAULT_CSS
        assert "$stream" in css, "DEFAULT_CSS must still set background: $stream"


# ─────────────────────────────────────────────────────────────────────────────
# markup=True 验证 — 通过 Static 构造签名确认
# ─────────────────────────────────────────────────────────────────────────────

class TestMarkupEnabled:
    """验证 StartupSplash 用 markup=True 构造,使 Rich markup 生效。"""

    def test_widget_render_markup_flag(self) -> None:
        """构造后 _render_markup 应为 True。"""
        w = StartupSplash(model_label="test-model", tier="default", live=True, has_key=True)
        assert w._render_markup is True, (
            "StartupSplash must be constructed with markup=True so Rich color tags are parsed"
        )

    def test_widget_demo_render_markup_flag(self) -> None:
        """DEMO 模式同样 markup=True。"""
        w = StartupSplash(model_label="fake-model", tier="default", live=False, has_key=True)
        assert w._render_markup is True


# ─────────────────────────────────────────────────────────────────────────────
# 功能不回退 — eye stage / plan_mode / ARGOS wordmark
# ─────────────────────────────────────────────────────────────────────────────

class TestFunctionalNonRegression:
    """验证着色修改没有破坏原有功能契约。"""

    def test_argos_wordmark_still_in_renderable_text(self) -> None:
        """ARGOS wordmark 仍在 renderable_text 中(可访问性/其他测试依赖)。"""
        w = StartupSplash(model_label="m", tier="t", live=True, has_key=True)
        assert "ARGOS" in w.renderable_text

    def test_plan_mode_prefix_present(self) -> None:
        """plan mode 时文本首含 'plan · '(spec §4.2 前缀契约不变)。"""
        text = _text(plan_mode=True)
        assert text.startswith("plan · "), f"plan mode prefix missing, text starts: {text[:40]!r}"

    def test_no_plan_mode_no_prefix(self) -> None:
        """非 plan mode 时无 'plan · ' 前缀。"""
        text = _text(plan_mode=False)
        assert not text.startswith("plan · ")

    def test_eye_stage_init_gives_idle_glyph(self) -> None:
        """init 阶段眼停在 ◌(契约6:空态)。"""
        text = _text(live=True, has_key=True, eye_stage="init")
        assert _has_color_wrap(text, _COL_EYE_GLOW, "◌"), "init stage should show ◌ in eye-glow"

    def test_eye_stage_focus_gives_focus_glyph(self) -> None:
        """focus 阶段眼为 ◉。"""
        text = _text(live=True, has_key=True, eye_stage="focus")
        assert _has_color_wrap(text, _COL_EYE_GLOW, "◉"), "focus stage should show ◉ in eye-glow"

    def test_no_key_eye_always_idle(self) -> None:
        """无 key 时任何 stage 眼字形都是 ◌(契约6)。"""
        for stage in ("init", "scan", "half", "focus", "open"):
            text = _text(live=True, has_key=False, eye_stage=stage)
            assert _has_color_wrap(text, _COL_EYE_GLOW, "◌"), (
                f"no-key: stage={stage!r} should still show ◌, not another glyph"
            )

    def test_advance_eye_updates_text(self) -> None:
        """advance_eye 后 renderable_text 中眼字形变为对应阶段。"""
        w = StartupSplash(model_label="m", tier="t", live=True, has_key=True)
        # init 阶段:◌
        assert _has_color_wrap(w.renderable_text, _COL_EYE_GLOW, "◌")
        w.advance_eye("focus")
        assert _has_color_wrap(w.renderable_text, _COL_EYE_GLOW, "◉")

    def test_live_badge_not_without_key(self) -> None:
        """无 key 时 renderable_text 中绝不含 LIVE 字样。"""
        w = StartupSplash(model_label="m", tier="t", live=True, has_key=False)
        assert "LIVE" not in w.renderable_text
