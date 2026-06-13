"""app.py 把图片 attachments 从 PromptArea 一路串到 loop.run(inline 路径)。"""
import pytest
from argos.tui.app import ArgosApp
from argos.tui.fakeloop import FakeLoop
from argos.input.attachments import ImageAttachment

_PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 16
_ATT = ImageAttachment(data=_PNG, media_type="image/png", source_label="clipboard")


@pytest.mark.asyncio
async def test_inline_run_threads_attachments_to_loop():
    """start_run(goal, [att]) → _start_run_inline → loop.run(attachments=[att])。"""
    fake = FakeLoop()
    app = ArgosApp(loop_factory=lambda: fake)
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        await app.start_run("看这张图", [_ATT])
        await pilot.pause()
    assert getattr(fake, "last_attachments", "MISSING") == [_ATT]


@pytest.mark.asyncio
async def test_handle_input_forwards_attachments_to_start_run():
    """handle_input(text, [att]) → start_run(text, [att])。"""
    app = ArgosApp(loop_factory=lambda: FakeLoop())
    captured = {}
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()

        async def fake_start_run(goal, attachments=None):
            captured["goal"] = goal
            captured["attachments"] = list(attachments or [])

        app.start_run = fake_start_run
        app.handle_input("看图", [_ATT])
        await pilot.pause()
    assert captured.get("goal") == "看图"
    assert captured.get("attachments") == [_ATT]


# ── Task 5: Ctrl+V 剪贴板贴图 ──
from argos.tui.widgets.prompt import PromptArea


@pytest.mark.asyncio
async def test_ctrl_v_inserts_image_token(monkeypatch):
    import argos.tui.app as appmod
    monkeypatch.setattr(appmod, "read_clipboard_image", lambda: _ATT)
    app = ArgosApp(loop_factory=lambda: FakeLoop())
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        await app.action_paste_image()
        await pilot.pause()
        pa = app.query_one("#prompt", PromptArea)
        assert "[图片 #1]" in pa.text


@pytest.mark.asyncio
async def test_ctrl_v_clipboard_error_is_honest(monkeypatch):
    import argos.tui.app as appmod

    def boom():
        raise appmod.ClipboardError("剪贴板里没有图片")

    monkeypatch.setattr(appmod, "read_clipboard_image", boom)
    app = ArgosApp(loop_factory=lambda: FakeLoop())
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        await app.action_paste_image()   # 不该抛
        await pilot.pause()
        pa = app.query_one("#prompt", PromptArea)
        assert "[图片" not in pa.text      # 失败不插 token
