# tests/test_transcript_widget.py
"""Transcript widget 测试:行为契约(不动语义) + v3 视觉断言。

v3 更新点:
  - 系统行前缀:◕(done)、◉(error)、⚠︎(escalation)、◌(system/faint)
  - 回合分隔字符:╌ (U+254C 半虚线)
  - UserMessage._render_markup is False 契约保持
"""
import pytest
from textual.app import App, ComposeResult
from argos_agent.tui.theme import ARGOS_NIGHT
from argos_agent.tui.widgets.transcript import (
    Transcript, UserMessage, AssistantMessage, SystemLine,
)


class _Harness(App):
    def __init__(self) -> None:
        super().__init__()
        # v3 token($ink-dim/$fail/$pass 等)须在 compose 之前注册
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
        await t.append_line("◉ 错误:boom", kind="error")
        await pilot.pause()
        lines = list(app.query(SystemLine))
        assert len(lines) == 1
        assert "boom" in t.rendered_text


@pytest.mark.asyncio
async def test_system_line_prefixes_v3():
    """v3 视觉断言:系统行前缀字形正确(◕/◉/⚠︎/◌)。"""
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
    """契约5:UserMessage._render_markup is False。"""
    msg = UserMessage("list[int] dict[str,Any] [/invalid-tag]")
    assert msg._render_markup is False, "UserMessage 必须关 Rich markup 防注入崩溃"


@pytest.mark.asyncio
async def test_scroll_position_preserved_when_user_scrolled_up():
    """修复"滚不动":用户向上翻历史后,流式 token / 系统行到达不得把视口拽回底部
    (此前每个写入无条件 scroll_end → 用户每次上滚被即时抵消,体感=滚动条失效)。"""
    app = _Harness()
    async with app.run_test(size=(80, 10)) as pilot:
        t = app.query_one("#t", Transcript)
        for i in range(40):
            await t.append_line(f"行 {i}", kind="system")
        await pilot.pause()
        assert t.max_scroll_y > 0, "内容应超出可视高度(可滚动)"
        t.scroll_to(y=0, animate=False)          # 用户向上滚到顶
        await pilot.pause()
        assert t.scroll_offset.y == 0
        await t.append_token("运行中新流入的回答")   # 流式 token 到达
        await pilot.pause()
        assert t.scroll_offset.y <= 2, \
            f"用户在顶部看历史时不应被流式内容拽到底部,实际 y={t.scroll_offset.y}"


@pytest.mark.asyncio
async def test_scroll_follows_when_already_at_bottom():
    """stick-to-bottom 正向行为:用户停在底部时,新内容应继续跟随到底(不破坏'实时跟读')。"""
    app = _Harness()
    async with app.run_test(size=(80, 10)) as pilot:
        t = app.query_one("#t", Transcript)
        for i in range(40):
            await t.append_line(f"行 {i}", kind="system")
        await pilot.pause()
        await t.append_token("继续流入")
        await pilot.pause()
        assert t.max_scroll_y - t.scroll_offset.y <= 2, "在底部时新内容应跟随到底"
