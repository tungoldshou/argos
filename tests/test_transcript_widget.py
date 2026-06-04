# tests/test_transcript_widget.py
import pytest
from textual.app import App, ComposeResult
from argos_agent.tui.widgets.transcript import (
    Transcript, UserMessage, AssistantMessage, SystemLine,
)


class _Harness(App):
    def compose(self) -> ComposeResult:
        yield Transcript(id="t")


@pytest.mark.asyncio
async def test_user_line_mounts_user_message():
    app = _Harness()
    async with app.run_test() as pilot:
        t = app.query_one("#t", Transcript)
        await t.user_line("修个 bug")
        await pilot.pause()
        msgs = list(app.query(UserMessage))
        assert len(msgs) == 1
        assert "修个 bug" in t.rendered_text


@pytest.mark.asyncio
async def test_append_token_streams_into_one_assistant_bubble_stripping_fences():
    app = _Harness()
    async with app.run_test() as pilot:
        t = app.query_one("#t", Transcript)
        await t.append_token("我来改\n```python\nwrite_file('a','b')\n```\n")
        await t.append_token("改完了。")
        await pilot.pause()
        assert len(list(app.query(AssistantMessage))) == 1, "同一段流式应进一个气泡"
        # 围栏代码不出现在散文气泡里(不漏 backtick / 不双显)
        assert "```" not in t.rendered_text
        assert "write_file" not in t.rendered_text
        assert "我来改" in t.rendered_text and "改完了" in t.rendered_text


@pytest.mark.asyncio
async def test_finalize_response_starts_new_bubble():
    app = _Harness()
    async with app.run_test() as pilot:
        t = app.query_one("#t", Transcript)
        await t.append_token("第一段")
        t.finalize_response()
        await t.append_token("第二段")
        await pilot.pause()
        assert len(list(app.query(AssistantMessage))) == 2, "finalize 后应起新气泡"


@pytest.mark.asyncio
async def test_append_line_mounts_system_line():
    app = _Harness()
    async with app.run_test() as pilot:
        t = app.query_one("#t", Transcript)
        await t.append_line("❌ 错误:boom", kind="error")
        await pilot.pause()
        lines = list(app.query(SystemLine))
        assert len(lines) == 1
        assert "boom" in t.rendered_text
