import pytest
from textual.app import App, ComposeResult
from argos_agent.tui.widgets.diff_view import DiffView


class _H(App):
    def compose(self) -> ComposeResult:
        yield DiffView(path="utils/range.py", added=1, removed=1,
                       unified="@@ -15 +15 @@\n-    range(0, len(xs)-n, n)\n+    range(0, len(xs), n)")


@pytest.mark.asyncio
async def test_diff_header_glyph_and_counts():
    app = _H()
    async with app.run_test() as pilot:
        await pilot.pause()
        dv = app.query_one(DiffView)
        assert "⏺" in str(dv.border_title)
        assert "utils/range.py" in str(dv.border_title)
        assert "┌" not in str(dv.border_title)
