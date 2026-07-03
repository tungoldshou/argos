# tests/test_transcript_widget.py
"""Internal documentation."""
import pytest
from textual.app import App, ComposeResult
from argos.tui.theme import ARGOS_NIGHT
from argos.tui.widgets.transcript import (
    Transcript, UserMessage, AssistantMessage, SystemLine,
)


class _Harness(App):
    def __init__(self) -> None:
        super().__init__()
        self.register_theme(ARGOS_NIGHT)
        self.theme = "argos-night"

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
        assert "```" not in t.rendered_text
        assert "write_file" not in t.rendered_text
        assert "我来改" in t.rendered_text and "改完了" in t.rendered_text


@pytest.mark.asyncio
async def test_append_token_survives_concurrent_finalize_during_mount():
    """Internal documentation."""
    app = _Harness()
    async with app.run_test() as pilot:
        t = app.query_one("#t", Transcript)
        orig_mount = t.mount
        calls = {"n": 0}

        async def _racing_mount(*a, **kw):
            res = await orig_mount(*a, **kw)
            calls["n"] += 1
            if calls["n"] == 1:
                t.finalize_response()
            return res

        t.mount = _racing_mount  # type: ignore[assignment]
        await t.append_token("```")
        await pilot.pause()
        assert list(app.query(AssistantMessage)), "应至少有一个 assistant 气泡(未崩)"


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
        await t.append_line("◉ 错误:boom", kind="error")
        await pilot.pause()
        lines = list(app.query(SystemLine))
        assert len(lines) == 1
        assert "boom" in t.rendered_text


@pytest.mark.asyncio
async def test_system_line_prefixes_v3():
    """Internal documentation."""
    app = _Harness()
    async with app.run_test() as pilot:
        t = app.query_one("#t", Transcript)
        await t.append_line("◕ run 完成 · 1.0s", kind="done")
        await t.append_line("◉ 模型连接中断:timeout", kind="error")
        await t.append_line("⚠︎ 连续 3 次 verify 失败", kind="escalation")
        await t.append_line("◌ 已压缩 -38%", kind="system")
        await pilot.pause()
        text = t.rendered_text
        assert "◕" in text,  "done 行应含 ◕ 阅毕眼"
        assert "◉" in text,  "error 行应含 ◉ 红瞳"
        assert "⚠︎" in text, "escalation 行应含 ⚠︎ (VS15)"
        assert "◌" in text,  "system/faint 行应含 ◌ 空态"


@pytest.mark.asyncio
async def test_user_message_markup_false():
    """Internal documentation."""
    msg = UserMessage("list[int] dict[str,Any] [/invalid-tag]")
    assert msg._render_markup is False, "UserMessage 必须关 Rich markup 防注入崩溃"


@pytest.mark.asyncio
async def test_scroll_position_preserved_when_user_scrolled_up():
    """Internal documentation."""
    app = _Harness()
    async with app.run_test(size=(80, 10)) as pilot:
        t = app.query_one("#t", Transcript)
        for i in range(40):
            await t.append_line(f"行 {i}", kind="system")
        await pilot.pause()
        assert t.max_scroll_y > 0, "内容应超出可视高度(可滚动)"
        t.scroll_to(y=0, animate=False)
        await pilot.pause()
        assert t.scroll_offset.y == 0
        await t.append_token("运行中新流入的回答")
        await pilot.pause()
        assert t.scroll_offset.y <= 2,\
            f"用户在顶部看历史时不应被流式内容拽到底部,实际 y={t.scroll_offset.y}"


@pytest.mark.asyncio
async def test_scroll_follows_when_already_at_bottom():
    """Internal documentation."""
    app = _Harness()
    async with app.run_test(size=(80, 10)) as pilot:
        t = app.query_one("#t", Transcript)
        for i in range(40):
            await t.append_line(f"行 {i}", kind="system")
        await pilot.pause()
        await t.append_token("继续流入")
        await pilot.pause()
        assert t.max_scroll_y - t.scroll_offset.y <= 2, "在底部时新内容应跟随到底"


@pytest.mark.asyncio
async def test_short_content_stays_at_top_not_bottom_anchored():
    """Internal documentation."""
    from textual.widgets import Static

    app = _Harness()
    async with app.run_test(size=(80, 40)) as pilot:
        t = app.query_one("#t", Transcript)
        short = Static("\n".join(f"logo {i}" for i in range(8)))
        await t.mount(short)
        await pilot.pause()
        await pilot.pause()
        assert t.max_scroll_y == 0, "矮内容不可滚动"
        assert short.region.y == 0,\
            f"矮于视口的内容应顶对齐(logo 在顶部),实际 region.y={short.region.y}"
        assert t.scroll_offset.y == 0,\
            f"空态不该有滚动偏移(底对齐会让其变负),实际 y={t.scroll_offset.y}"


@pytest.mark.asyncio
async def test_scroll_follows_during_burst_of_events():
    """Internal documentation."""
    from textual.widgets import Static

    class _Tall(Static):
        def __init__(self, n: int, tag: str) -> None:
            super().__init__("\n".join(f"{tag}{i}" for i in range(n)))

    app = _Harness()
    async with app.run_test(size=(80, 12)) as pilot:
        t = app.query_one("#t", Transcript)
        for i in range(20):
            await t.append_line(f"sys {i}")
        await pilot.pause()
        for i in range(60):
            await t.append_token(f"tok{i} filler text that wraps eventually maybe\n")
        await pilot.pause()
        assert t.max_scroll_y - t.scroll_offset.y <= 2,\
            f"流式成批到达后应跟随到底,实际 off={t.scroll_offset.y} max={t.max_scroll_y}"
        for s in range(6):
            await t.append_line(f"python step {s}")
            await t.mount_block(_Tall(20, f"r{s}_"))
        await pilot.pause()
        assert t.max_scroll_y - t.scroll_offset.y <= 2,\
            f"密集 step+结果块后应跟随到底,实际 off={t.scroll_offset.y} max={t.max_scroll_y}"
