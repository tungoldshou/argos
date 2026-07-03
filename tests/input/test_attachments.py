from __future__ import annotations

import base64
import os
import tempfile

import pytest


# ── Task 1: ImageAttachment dataclass ─────────────────────────────────────────

def test_image_attachment_basic_construction():
    from argos.input.attachments import ImageAttachment
    att = ImageAttachment(data=b"\x89PNG", media_type="image/png", source_label="test.png")
    assert att.data == b"\x89PNG"
    assert att.media_type == "image/png"
    assert att.source_label == "test.png"


def test_image_attachment_optional_fields_default():
    from argos.input.attachments import ImageAttachment
    att = ImageAttachment(data=b"x", media_type="image/jpeg", source_label="x.jpg")
    assert att.width is None
    assert att.height is None


def test_image_attachment_with_dimensions():
    from argos.input.attachments import ImageAttachment
    att = ImageAttachment(data=b"x", media_type="image/png", source_label="x.png",
                          width=800, height=600)
    assert att.width == 800
    assert att.height == 600


def test_image_attachment_is_immutable():
    from argos.input.attachments import ImageAttachment
    att = ImageAttachment(data=b"x", media_type="image/png", source_label="x.png")
    with pytest.raises((AttributeError, TypeError)):
        att.data = b"y"  # type: ignore[misc]



def test_sniff_media_type_png():
    from argos.input.attachments import sniff_media_type
    png_header = b"\x89PNG\r\n\x1a\n" + b"\x00" * 10
    assert sniff_media_type(png_header) == "image/png"


def test_sniff_media_type_jpeg():
    from argos.input.attachments import sniff_media_type
    jpeg_header = b"\xff\xd8\xff\xe0" + b"\x00" * 10
    assert sniff_media_type(jpeg_header) == "image/jpeg"


def test_sniff_media_type_webp():
    from argos.input.attachments import sniff_media_type
    webp = b"RIFF\x00\x00\x00\x00WEBP"
    assert sniff_media_type(webp) == "image/webp"


def test_sniff_media_type_gif():
    from argos.input.attachments import sniff_media_type
    assert sniff_media_type(b"GIF87a" + b"\x00" * 10) == "image/gif"
    assert sniff_media_type(b"GIF89a" + b"\x00" * 10) == "image/gif"


def test_sniff_media_type_unknown_raises():
    from argos.input.attachments import sniff_media_type
    with pytest.raises(ValueError, match="unsupported"):
        sniff_media_type(b"\x00\x00\x00\x00")



def test_validate_attachment_ok():
    from argos.input.attachments import ImageAttachment, validate_attachment
    att = ImageAttachment(data=b"\x89PNG" + b"\x00" * 100,
                          media_type="image/png", source_label="ok.png")
    validate_attachment(att)


def test_validate_attachment_too_large():
    from argos.input.attachments import ImageAttachment, validate_attachment
    big = ImageAttachment(data=b"\x00" * (5 * 1024 * 1024 + 1),
                          media_type="image/png", source_label="big.png")
    with pytest.raises(ValueError, match="5MB"):
        validate_attachment(big)


def test_validate_attachment_unsupported_type():
    from argos.input.attachments import ImageAttachment, validate_attachment
    att = ImageAttachment(data=b"BM" + b"\x00" * 10,
                          media_type="image/bmp", source_label="x.bmp")
    with pytest.raises(ValueError, match="unsupported|不支持"):
        validate_attachment(att)



def test_to_base64_returns_str():
    from argos.input.attachments import ImageAttachment, to_base64
    att = ImageAttachment(data=b"hello", media_type="image/png", source_label="x.png")
    result = to_base64(att)
    assert isinstance(result, str)
    assert result == base64.b64encode(b"hello").decode()



def test_extract_image_paths_finds_png():
    from argos.input.attachments import extract_image_paths
    text = "请分析这张图 /tmp/screenshot.png 并告诉我结果"
    paths = extract_image_paths(text)
    assert "/tmp/screenshot.png" in paths


def test_extract_image_paths_finds_multiple():
    from argos.input.attachments import extract_image_paths
    text = "图1: /a/b.png 图2: /c/d.jpg"
    paths = extract_image_paths(text)
    assert "/a/b.png" in paths
    assert "/c/d.jpg" in paths


def test_extract_image_paths_no_match():
    from argos.input.attachments import extract_image_paths
    assert extract_image_paths("just some text") == []


def test_extract_image_paths_ignores_non_image():
    from argos.input.attachments import extract_image_paths
    paths = extract_image_paths("look at /some/file.py please")
    assert "/some/file.py" not in paths


# ── Task 6: load_from_path ────────────────────────────────────────────────────

def test_load_from_path_reads_real_file():
    from argos.input.attachments import load_from_path
    minimal_png = (
        b'\x89PNG\r\n\x1a\n'                         # signature
        b'\x00\x00\x00\rIHDR'                         # IHDR chunk length+type
        b'\x00\x00\x00\x01\x00\x00\x00\x01'          # 1x1
        b'\x08\x02\x00\x00\x00\x90wS\xde'            # bit_depth etc + CRC
        b'\x00\x00\x00\x0cIDATx\x9cc\xf8\x0f\x00\x00\x01\x01\x00\x05\x18\xd8N'  # IDAT
        b'\x00\x00\x00\x00IEND\xaeB`\x82'            # IEND
    )
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
        f.write(minimal_png)
        fname = f.name
    try:
        att = load_from_path(fname)
        assert att.media_type == "image/png"
        assert att.data == minimal_png
        assert fname in att.source_label or os.path.basename(fname) in att.source_label
    finally:
        os.unlink(fname)


def test_load_from_path_missing_file_raises():
    from argos.input.attachments import load_from_path
    with pytest.raises(FileNotFoundError):
        load_from_path("/nonexistent/path/image.png")
