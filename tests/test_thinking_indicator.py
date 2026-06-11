# tests/test_thinking_indicator.py
"""ThinkingIndicator 测试:行为契约 + v3 视觉断言。

v3 更新点:
  - CSS token 从 $accent 改为 $eye(金系主强调)
  - 眼慢眨:~4s 周期 ◉→◓→◉ 两帧(静态字形,非动画循环)
  - braille spinner 帧序列保持不变
"""
import pytest
from textual.app import App, ComposeResult
from argos_agent.tui.theme import ARGOS_NIGHT
from argos_agent.tui.widgets.thinking import ThinkingIndicator, _FRAMES, _BLINK_GLYPHS


class _H(App):
    def __init__(self) -> None:
        super().__init__()
        # v3 token($eye 等)须在 compose 之前注册,否则 DEFAULT_CSS 解析抛 UnresolvedVariableError
        self.register_theme(ARGOS_NIGHT)
        self.theme = "argos-night"

    def compose(self) -> ComposeResult:
        yield ThinkingIndicator(id="th")


@pytest.mark.asyncio
async def test_spinner_cycles_glyph():
    app = _H()
    async with app.run_test() as pilot:
        await pilot.pause()
        th = app.query_one("#th", ThinkingIndicator)
        first = th._frame
        th._tick()
        assert th._frame != first, "tick 应推进 spinner 帧"
        assert th.renderable  # 有内容


def test_braille_frames_sequence():
    """行为契约:braille 帧序列固定为 10 帧(v2 已验证不变)。"""
    assert len(_FRAMES) == 10, "braille spinner 必须恰好 10 帧"
    assert _FRAMES[0] == "⠋"
    assert _FRAMES[-1] == "⠏"


def test_css_token_is_eye():
    """v3 视觉断言:CSS 颜色 token 应为 $eye(金系主强调),不再用 $accent。"""
    assert "$eye" in ThinkingIndicator.DEFAULT_CSS, \
        "ThinkingIndicator DEFAULT_CSS 应使用 $eye token(v3 规范)"
    assert "$accent" not in ThinkingIndicator.DEFAULT_CSS, \
        "v3 中 $accent 已废弃,应改用 $eye"


def test_blink_glyphs_defined():
    """v3 眼慢眨:◉→◓→◉ 两帧字形已定义在模块级常量 _BLINK_GLYPHS。"""
    assert "◉" in _BLINK_GLYPHS, "慢眨帧应包含 ◉ (U+25C9 注视/act)"
    assert "◓" in _BLINK_GLYPHS, "慢眨帧应包含 ◓ (U+25D3 半阖/等待)"


@pytest.mark.asyncio
async def test_renderable_contains_braille_frame():
    """每次 render 必含 braille 帧字形之一。"""
    app = _H()
    async with app.run_test() as pilot:
        await pilot.pause()
        th = app.query_one("#th", ThinkingIndicator)
        text = th.renderable
        assert any(c in text for c in _FRAMES), \
            f"renderable 应含 braille 帧,实际: {text!r}"
