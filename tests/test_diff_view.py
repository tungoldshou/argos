import pytest
from textual.app import App, ComposeResult

from argos.tui.theme import ARGOS_NIGHT
from argos.tui.widgets.diff_view import DiffView

_UNIFIED = "@@ -15 +15 @@\n-    range(0, len(xs)-n, n)\n+    range(0, len(xs), n)"


class _H(App):

    def get_theme_variable_defaults(self) -> dict[str, str]:
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




def test_public_attrs_preserved():
    dv = DiffView(path="auth.py", added=3, removed=1, unified=_UNIFIED)
    assert dv.path == "auth.py"
    assert dv.added == 3
    assert dv.removed == 1
    assert dv.unified == _UNIFIED




def test_border_title_contains_path_no_glyph_prefix():
    dv = DiffView(path="auth.py", added=3, removed=1, unified=_UNIFIED)
    title = str(dv.border_title)
    assert "auth.py" in title
    assert "Edit" in title
    assert "⏺" not in title


def test_border_subtitle_uses_unicode_minus():
    dv = DiffView(path="auth.py", added=3, removed=1, unified=_UNIFIED)
    sub = str(dv.border_subtitle)
    assert "+3" in sub
    # U+2212 MINUS SIGN
    assert "−" in sub or "−" in sub


def test_border_subtitle_values():
    dv = DiffView(path="x.py", added=5, removed=2, unified=_UNIFIED)
    sub = str(dv.border_subtitle)
    assert "5" in sub
    assert "2" in sub


@pytest.mark.asyncio
async def test_border_left_only_no_round():
    app = _H()
    async with app.run_test() as pilot:
        await pilot.pause()
        dv = app.query_one(DiffView)
        css = DiffView.DEFAULT_CSS
        assert "border-left" in css
        assert "border: round" not in css
        assert "$hairline-lit" in css


@pytest.mark.asyncio
async def test_background_is_raise_token():
    app = _H()
    async with app.run_test() as pilot:
        await pilot.pause()
        css = DiffView.DEFAULT_CSS
        assert "$raise" in css


@pytest.mark.asyncio
async def test_diff_path_in_title():
    app = _H()
    async with app.run_test() as pilot:
        await pilot.pause()
        dv = app.query_one(DiffView)
        assert "utils/range.py" in str(dv.border_title)
