from argos.tui.widgets.prompt import PromptArea
from argos.input.attachments import ImageAttachment

_PNG = b"\x89PNG\r\n\x1a\n\x00\x00\x00\x0dIHDR" + b"\x00\x00\x00\x0a\x00\x00\x00\x0a" + b"\x00" * 5
_ATT = ImageAttachment(data=_PNG, media_type="image/png", source_label="clipboard")


def _fresh() -> PromptArea:
    return PromptArea()


def test_short_paste_no_token():
    pa = _fresh()
    assert pa._make_paste_token("short text") is None


def test_long_paste_makes_token_and_stores():
    pa = _fresh()
    big = "x" * 10001
    token = pa._make_paste_token(big)
    assert token is not None and token.startswith("[粘贴文本 #1")
    expanded, atts = pa._expand_submission(token)
    assert expanded == big
    assert atts == []


def test_long_paste_token_counts_lines():
    pa = _fresh()
    big = "x" * 9000 + "\n" * 2000
    token = pa._make_paste_token(big)
    assert "+2000 行" in token


def test_register_image_returns_token_and_expands_to_attachment():
    pa = _fresh()
    token = pa.register_image(_ATT)
    assert token == "[图片 #1]"
    expanded, atts = pa._expand_submission(f"看 {token} 这里")
    assert atts == [_ATT]
    assert token not in expanded


def test_expand_collects_file_path(tmp_path):
    pa = _fresh()
    p = tmp_path / "shot.png"
    p.write_bytes(_PNG)
    expanded, atts = pa._expand_submission(f"看 {p}")
    assert len(atts) == 1 and atts[0].media_type == "image/png"


def test_expand_skips_bad_image_path(tmp_path):
    pa = _fresh()
    p = tmp_path / "notes.png"
    p.write_text("not an image")
    expanded, atts = pa._expand_submission(f"看 {p}")
    assert atts == []


def test_submitted_carries_attachments():
    msg = PromptArea.Submitted("hi", [_ATT])
    assert msg.text == "hi"
    assert msg.attachments == [_ATT]


def test_submitted_attachments_default_empty():
    msg = PromptArea.Submitted("hi")
    assert msg.attachments == []


import pytest
from textual import events
from textual.app import App
from argos.tui.theme import ARGOS_NIGHT


class _ThemeHost(App):
    def get_theme_variable_defaults(self) -> dict[str, str]:
        return ARGOS_NIGHT.variables

    def compose(self):
        yield PromptArea(id="p")


@pytest.mark.asyncio
async def test_on_paste_long_text_inserts_token_not_raw():
    app = _ThemeHost()
    async with app.run_test():
        pa = app.query_one("#p", PromptArea)
        big = "y" * 10050
        await pa._on_paste(events.Paste(big))
        assert "[粘贴文本 #1" in pa.text
        assert "y" * 10050 not in pa.text
        assert any(v == big for v in pa._paste_store.values())


@pytest.mark.asyncio
async def test_on_paste_short_text_inlines():
    app = _ThemeHost()
    async with app.run_test():
        pa = app.query_one("#p", PromptArea)
        await pa._on_paste(events.Paste("hello"))
        assert "hello" in pa.text
        assert pa._paste_store == {}


@pytest.mark.asyncio
async def test_empty_space_stays_in_prompt():
    captured = []

    class _H(_ThemeHost):
        def on_prompt_area_submitted(self, event):
            captured.append(event)

    app = _H()
    async with app.run_test() as pilot:
        pa = app.query_one("#p", PromptArea)
        pa.focus()
        await pilot.press("space")
        await pilot.pause()
        assert captured == []
        assert pa.text == " "


@pytest.mark.asyncio
async def test_nonempty_space_is_normal_text():
    app = _ThemeHost()
    async with app.run_test() as pilot:
        pa = app.query_one("#p", PromptArea)
        pa.focus()
        pa.insert("hello")
        await pilot.press("space")
        await pilot.pause()
        assert pa.text.endswith(" ")


@pytest.mark.asyncio
async def test_enter_submits_expanded_text():
    captured = []

    class _H(_ThemeHost):
        def on_prompt_area_submitted(self, event):
            captured.append(event)

    app = _H()
    async with app.run_test() as pilot:
        pa = app.query_one("#p", PromptArea)
        pa.focus()
        big = "z" * 10050
        await pa._on_paste(events.Paste(big))
        await pilot.press("enter")
        await pilot.pause()
        assert len(captured) == 1
        assert captured[0].text == big
        assert captured[0].attachments == []
