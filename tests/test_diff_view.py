"""DiffView 视觉快照测试(TUI v3 · 黑曜石之眼 spec §4.5)。

断言点:
- border_title 包含 path、不含旧 ⏺ 前缀(v3 改纯文字)
- border_subtitle 含 "+N −M"(中文减号 −,U+2212)
- DEFAULT_CSS 是仅左缘 border-left tall(不是 round 全框)
- 公开属性 path/added/removed/unified 保持(API 兼容)
"""
import pytest
from textual.app import App, ComposeResult

from argos.tui.theme import ARGOS_NIGHT
from argos.tui.widgets.diff_view import DiffView

_UNIFIED = "@@ -15 +15 @@\n-    range(0, len(xs)-n, n)\n+    range(0, len(xs), n)"


class _H(App):
    """最小测试宿主：注入 argos-night token 以便 DEFAULT_CSS 中 $token 在 CSS 解析阶段可用。

    get_theme_variable_defaults() 在 DEFAULT_CSS 首次解析前运行,
    是让自定义 $token 在测试环境中可用的唯一手段。
    """

    def get_theme_variable_defaults(self) -> dict[str, str]:
        """把 ARGOS_NIGHT.variables 作为 CSS token 兜底注入。"""
        defaults = super().get_theme_variable_defaults()
        if ARGOS_NIGHT.variables:
            defaults.update(ARGOS_NIGHT.variables)
        return defaults

    def compose(self) -> ComposeResult:
        yield DiffView(
            path="utils/range.py",
            added=3,
            removed=1,
            unified=_UNIFIED,
        )


# ── API 兼容(行为契约,语义不变)──────────────────────────────────────


def test_public_attrs_preserved():
    """公开属性 path/added/removed/unified 兼容。"""
    dv = DiffView(path="auth.py", added=3, removed=1, unified=_UNIFIED)
    assert dv.path == "auth.py"
    assert dv.added == 3
    assert dv.removed == 1
    assert dv.unified == _UNIFIED


# ── 视觉快照(v3 新设计)────────────────────────────────────────────


def test_border_title_contains_path_no_glyph_prefix():
    """v3: border_title = 'Edit · {path}',去掉 ⏺ 前缀。"""
    dv = DiffView(path="auth.py", added=3, removed=1, unified=_UNIFIED)
    title = str(dv.border_title)
    # v3 规范:纯文字 "Edit · {path}",不含 ⏺
    assert "auth.py" in title
    assert "Edit" in title
    assert "⏺" not in title


def test_border_subtitle_uses_unicode_minus():
    """v3: border_subtitle = '+{added} −{removed}',减号用 U+2212 不是 ASCII '-'。"""
    dv = DiffView(path="auth.py", added=3, removed=1, unified=_UNIFIED)
    sub = str(dv.border_subtitle)
    assert "+3" in sub
    # U+2212 MINUS SIGN
    assert "−" in sub or "−" in sub


def test_border_subtitle_values():
    """border_subtitle 数字正确。"""
    dv = DiffView(path="x.py", added=5, removed=2, unified=_UNIFIED)
    sub = str(dv.border_subtitle)
    assert "5" in sub
    assert "2" in sub


@pytest.mark.asyncio
async def test_border_left_only_no_round():
    """v3: 仅左缘 border-left tall,不是 round 全框。"""
    app = _H()
    async with app.run_test() as pilot:
        await pilot.pause()
        dv = app.query_one(DiffView)
        css = DiffView.DEFAULT_CSS
        # 必须含 border-left
        assert "border-left" in css
        # 不得含 "border: round"(v2 旧设计)
        assert "border: round" not in css
        # border-left 使用 $hairline-lit token
        assert "$hairline-lit" in css


@pytest.mark.asyncio
async def test_background_is_raise_token():
    """v3: background 使用 $raise 浮起面 token。"""
    app = _H()
    async with app.run_test() as pilot:
        await pilot.pause()
        css = DiffView.DEFAULT_CSS
        assert "$raise" in css


@pytest.mark.asyncio
async def test_diff_path_in_title():
    """集成:Textual pilot 下 border_title 含 path。"""
    app = _H()
    async with app.run_test() as pilot:
        await pilot.pause()
        dv = app.query_one(DiffView)
        assert "utils/range.py" in str(dv.border_title)
