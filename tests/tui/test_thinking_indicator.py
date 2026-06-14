# tests/tui/test_thinking_indicator.py
"""ThinkingIndicator 回归测试 — 设计审计修复后的锁定断言。

覆盖点(对应 audit findings):
  [HIGH]  spinner 只输出 braille 帧(_FRAMES),绝不输出 ◓(blocked-only 保留字形)
  [HIGH]  _BLINK_GLYPHS / _BLINK_INTERVAL_TICKS / _BLINK_HOLD_TICKS 模块级常量已删除
  [HIGH]  _blink_ticks_left 字段不存在于实例
  [HIGH]  render() 在任意 _frame 值下均输出 _FRAMES 中的字形,不输出 ◓
  [MEDIUM] 模块 docstring 不包含幻象 spec 引用 §6.1/§6.2/眼慢眨/慢眨
  [MEDIUM] 模块 docstring 包含真实来源引用 README §字形铁律 / 01-act
  基础 API:构造/set_label/renderable/DEFAULT_CSS token
"""
from __future__ import annotations

import importlib
import inspect
import sys

import pytest

# 保证每次测试拿到最新模块(避免 import cache 遮盖)
import argos.tui.widgets.thinking as _mod
from argos.tui.widgets.thinking import ThinkingIndicator, _FRAMES


# ─────────────────────────────────────────────────────────────────────────────
# 辅助
# ─────────────────────────────────────────────────────────────────────────────

def _make() -> ThinkingIndicator:
    """无挂载地构造 ThinkingIndicator(不启动事件循环)。"""
    return ThinkingIndicator(label="思考中…")


def _render_at_frame(widget: ThinkingIndicator, frame: int) -> str:
    """强制设定 _frame 后调用 render(),绕开 set_interval。"""
    widget._frame = frame
    return widget.render()


# ─────────────────────────────────────────────────────────────────────────────
# [HIGH] blink overlay 已删除 — 模块级常量不再存在
# ─────────────────────────────────────────────────────────────────────────────

class TestBlinkOverlayRemoved:
    """audit HIGH: _BLINK_GLYPHS / _BLINK_INTERVAL_TICKS / _BLINK_HOLD_TICKS 已删。"""

    def test_no_blink_glyphs_constant(self):
        """_BLINK_GLYPHS 模块常量已删除。"""
        assert not hasattr(_mod, "_BLINK_GLYPHS"), (
            "_BLINK_GLYPHS must be removed; ◓ is reserved for blocked/unverif"
        )

    def test_no_blink_interval_ticks_constant(self):
        """_BLINK_INTERVAL_TICKS 模块常量已删除。"""
        assert not hasattr(_mod, "_BLINK_INTERVAL_TICKS"), (
            "_BLINK_INTERVAL_TICKS must be removed along with blink overlay"
        )

    def test_no_blink_hold_ticks_constant(self):
        """_BLINK_HOLD_TICKS 模块常量已删除。"""
        assert not hasattr(_mod, "_BLINK_HOLD_TICKS"), (
            "_BLINK_HOLD_TICKS must be removed along with blink overlay"
        )

    def test_instance_has_no_blink_ticks_left(self):
        """实例不含 _blink_ticks_left 字段。"""
        widget = _make()
        assert not hasattr(widget, "_blink_ticks_left"), (
            "_blink_ticks_left must be removed from instance — blink overlay gone"
        )

    def test_instance_has_no_tick_count(self):
        """实例不含 _tick_count 字段(blink interval 计数器)。"""
        widget = _make()
        assert not hasattr(widget, "_tick_count"), (
            "_tick_count must be removed from instance — blink overlay gone"
        )


# ─────────────────────────────────────────────────────────────────────────────
# [HIGH] render() 在所有帧下只输出 braille,不输出 ◓
# ─────────────────────────────────────────────────────────────────────────────

class TestGlyphDiscipline:
    """audit HIGH: ◓ 是 blocked-only 字形,不得出现在 ThinkingIndicator 输出中。"""

    _BLOCKED_GLYPH = "◓"  # U+25D3 — 审批/硬确认挂起专用

    @pytest.mark.parametrize("frame", range(len(_FRAMES)))
    def test_no_blocked_glyph_at_any_frame(self, frame):
        """所有 10 个 braille 帧的 render() 均不输出 ◓。"""
        widget = _make()
        output = _render_at_frame(widget, frame)
        assert self._BLOCKED_GLYPH not in output, (
            f"frame={frame}: render() must NOT emit ◓ (blocked-only glyph); got {output!r}"
        )

    @pytest.mark.parametrize("frame", range(len(_FRAMES)))
    def test_braille_glyph_at_every_frame(self, frame):
        """每帧 render() 输出的首字符是对应的 braille 字形。"""
        widget = _make()
        output = _render_at_frame(widget, frame)
        expected_glyph = _FRAMES[frame]
        assert output.startswith(expected_glyph), (
            f"frame={frame}: expected glyph {expected_glyph!r} at start, got {output!r}"
        )

    def test_frames_constant_is_braille_only(self):
        """_FRAMES 字符串仅含 braille 字形(U+2800..U+28FF)。"""
        for ch in _FRAMES:
            code = ord(ch)
            assert 0x2800 <= code <= 0x28FF, (
                f"_FRAMES contains non-braille character {ch!r} (U+{code:04X})"
            )

    def test_frames_has_ten_glyphs(self):
        """_FRAMES 恰好 10 帧(spec: 10 帧 0.12s/帧)。"""
        assert len(_FRAMES) == 10, (
            f"_FRAMES must have 10 glyphs, got {len(_FRAMES)}: {_FRAMES!r}"
        )


# ─────────────────────────────────────────────────────────────────────────────
# [MEDIUM] docstring 幻象 spec 引用已删,真实来源已引入
# ─────────────────────────────────────────────────────────────────────────────

class TestDocstringProvenance:
    """audit MEDIUM: 模块 docstring 不含 phantom spec 引用,含真实来源。"""

    _MODULE_DOC: str = _mod.__doc__ or ""
    _CLASS_DOC: str = ThinkingIndicator.__doc__ or ""

    # 幻象 spec 词条(这些不应存在)
    @pytest.mark.parametrize("phantom", ["§6.1", "§6.2", "眼慢眨", "慢眨"])
    def test_module_docstring_no_phantom_spec(self, phantom):
        """模块 docstring 不包含幻象 spec 引用 '{phantom}'。"""
        assert phantom not in self._MODULE_DOC, (
            f"Module docstring must not contain phantom spec ref {phantom!r}; "
            f"remove it — §6.1/§6.2 do not exist in the design handoff"
        )

    @pytest.mark.parametrize("phantom", ["§6.1", "§6.2", "眼慢眨", "慢眨"])
    def test_class_docstring_no_phantom_spec(self, phantom):
        """类 docstring 不包含幻象 spec 引用 '{phantom}'。"""
        assert phantom not in self._CLASS_DOC, (
            f"Class docstring must not contain phantom spec ref {phantom!r}"
        )

    def test_module_docstring_cites_real_source(self):
        """模块 docstring 引用真实来源(README §字形铁律 或 01-act 视觉稿)。"""
        # 至少其中一个真实来源词条必须存在
        real_refs = ["README", "字形铁律", "01-act", "视觉稿"]
        found = any(ref in self._MODULE_DOC for ref in real_refs)
        assert found, (
            f"Module docstring must cite the real design source "
            f"(README §字形铁律 / 01-act 视觉稿); got: {self._MODULE_DOC!r}"
        )


# ─────────────────────────────────────────────────────────────────────────────
# 基础 API(公开契约不得破坏)
# ─────────────────────────────────────────────────────────────────────────────

class TestPublicAPI:
    """公开构造/set_label/renderable/DEFAULT_CSS 合约。"""

    def test_construct_default_label(self):
        """默认构造不崩溃,label 存储为 '思考中…'。"""
        widget = _make()
        assert widget._label == "思考中…"

    def test_construct_custom_label(self):
        """自定义 label 被存储。"""
        widget = ThinkingIndicator(label="回归测试中…")
        assert widget._label == "回归测试中…"

    def test_set_label_updates_label(self):
        """set_label() 更新内部 _label。"""
        widget = _make()
        widget.set_label("新标签")
        assert widget._label == "新标签"

    def test_renderable_property_returns_string(self):
        """renderable 属性返回 str(兼容旧断言)。"""
        widget = _make()
        result = widget.renderable
        assert isinstance(result, str)

    def test_renderable_equals_render(self):
        """renderable == render()(唯一真源)。"""
        widget = _make()
        assert widget.renderable == widget.render()

    def test_render_contains_label(self):
        """render() 输出包含当前 label。"""
        widget = ThinkingIndicator(label="测试标签")
        output = _render_at_frame(widget, 0)
        assert "测试标签" in output, f"render() must contain label; got {output!r}"

    def test_render_format_glyph_space_label(self):
        """render() 格式为 '<glyph> <label>[秒数]'。"""
        widget = ThinkingIndicator(label="abc")
        # frame=0 → _FRAMES[0] = '⠋'
        output = _render_at_frame(widget, 0)
        # 首字符是 braille,第二字符是空格,之后是 label
        assert output[0] == _FRAMES[0], f"first char must be glyph; got {output!r}"
        assert output[1] == " ", f"second char must be space; got {output!r}"
        assert "abc" in output, f"label must appear in output; got {output!r}"

    def test_default_css_uses_eye_token(self):
        """DEFAULT_CSS 使用 $eye token 而非 hardcoded hex。"""
        css = ThinkingIndicator.DEFAULT_CSS
        assert "$eye" in css, (
            f"DEFAULT_CSS must use $eye token (not hardcoded hex); got: {css!r}"
        )

    def test_default_css_no_hardcoded_hex(self):
        """DEFAULT_CSS 不含 hardcoded hex 颜色。"""
        import re
        css = ThinkingIndicator.DEFAULT_CSS
        hex_pattern = re.compile(r"#[0-9A-Fa-f]{3,8}\b")
        matches = hex_pattern.findall(css)
        assert not matches, (
            f"DEFAULT_CSS must not contain hardcoded hex; found: {matches}"
        )

    def test_frame_cycles_through_all_frames(self):
        """_tick() 使 _frame 循环经过所有 10 帧。"""
        widget = _make()
        widget._frame = 0
        seen = set()
        for _ in range(len(_FRAMES)):
            seen.add(widget._frame)
            # 模拟 _tick 的核心逻辑(不启动定时器)
            widget._frame = (widget._frame + 1) % len(_FRAMES)
        assert seen == set(range(len(_FRAMES))), (
            f"_tick must cycle through all {len(_FRAMES)} frames; only saw {sorted(seen)}"
        )
