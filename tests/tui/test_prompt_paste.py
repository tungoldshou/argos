"""PromptArea 粘贴管线纯逻辑:占位 token 生成 + 提交展开(无需挂载 app)。"""
from argos.tui.widgets.prompt import PromptArea
from argos.input.attachments import ImageAttachment

_PNG = b"\x89PNG\r\n\x1a\n\x00\x00\x00\x0dIHDR" + b"\x00\x00\x00\x0a\x00\x00\x00\x0a" + b"\x00" * 5
_ATT = ImageAttachment(data=_PNG, media_type="image/png", source_label="clipboard")


def _fresh() -> PromptArea:
    return PromptArea()


def test_short_paste_no_token():
    pa = _fresh()
    assert pa._make_paste_token("short text") is None  # 短文本不占位


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
    big = "x" * 9000 + "\n" * 2000  # >10000 字符,含 2000 换行
    token = pa._make_paste_token(big)
    assert "+2000 行" in token


def test_register_image_returns_token_and_expands_to_attachment():
    pa = _fresh()
    token = pa.register_image(_ATT)
    assert token == "[图片 #1]"
    expanded, atts = pa._expand_submission(f"看 {token} 这里")
    assert atts == [_ATT]
    assert token not in expanded  # 图片占位符不进文本


def test_expand_collects_file_path(tmp_path):
    pa = _fresh()
    p = tmp_path / "shot.png"
    p.write_bytes(_PNG)
    expanded, atts = pa._expand_submission(f"看 {p}")
    assert len(atts) == 1 and atts[0].media_type == "image/png"


def test_expand_skips_bad_image_path(tmp_path):
    """文本里的非图片路径 → 跳过不附,文本保留(诚实降级)。"""
    pa = _fresh()
    p = tmp_path / "notes.png"        # .png 后缀但内容非图
    p.write_text("not an image")
    expanded, atts = pa._expand_submission(f"看 {p}")
    assert atts == []                  # sniff 抛 ValueError → 跳过


def test_submitted_carries_attachments():
    msg = PromptArea.Submitted("hi", [_ATT])
    assert msg.text == "hi"
    assert msg.attachments == [_ATT]


def test_submitted_attachments_default_empty():
    msg = PromptArea.Submitted("hi")
    assert msg.attachments == []
