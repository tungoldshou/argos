"""attachments.py TDD 验收套件 — ImageAttachment dataclass / 路径检测 / 校验 / media_type 嗅探 / base64。

本文件对应 spec §4(input/ 子包)+ §5(方案 C 边车 attachments)。
"""
from __future__ import annotations

import base64
import os
import tempfile

import pytest


# ── Task 1: ImageAttachment dataclass ─────────────────────────────────────────

def test_image_attachment_basic_construction():
    """ImageAttachment 可用最小字段构造(data + media_type + source_label)。"""
    from argos_agent.input.attachments import ImageAttachment
    att = ImageAttachment(data=b"\x89PNG", media_type="image/png", source_label="test.png")
    assert att.data == b"\x89PNG"
    assert att.media_type == "image/png"
    assert att.source_label == "test.png"


def test_image_attachment_optional_fields_default():
    """width / height 未传时默认 None(可选元数据)。"""
    from argos_agent.input.attachments import ImageAttachment
    att = ImageAttachment(data=b"x", media_type="image/jpeg", source_label="x.jpg")
    assert att.width is None
    assert att.height is None


def test_image_attachment_with_dimensions():
    """width / height 可选传入并保留。"""
    from argos_agent.input.attachments import ImageAttachment
    att = ImageAttachment(data=b"x", media_type="image/png", source_label="x.png",
                          width=800, height=600)
    assert att.width == 800
    assert att.height == 600


def test_image_attachment_is_immutable():
    """ImageAttachment 应为不可变 dataclass(frozen=True)。"""
    from argos_agent.input.attachments import ImageAttachment
    att = ImageAttachment(data=b"x", media_type="image/png", source_label="x.png")
    with pytest.raises((AttributeError, TypeError)):
        att.data = b"y"  # type: ignore[misc]


# ── Task 2: media_type 嗅探 ────────────────────────────────────────────────────

def test_sniff_media_type_png():
    """PNG 字节头 → 'image/png'。"""
    from argos_agent.input.attachments import sniff_media_type
    png_header = b"\x89PNG\r\n\x1a\n" + b"\x00" * 10
    assert sniff_media_type(png_header) == "image/png"


def test_sniff_media_type_jpeg():
    """JPEG 字节头(FF D8) → 'image/jpeg'。"""
    from argos_agent.input.attachments import sniff_media_type
    jpeg_header = b"\xff\xd8\xff\xe0" + b"\x00" * 10
    assert sniff_media_type(jpeg_header) == "image/jpeg"


def test_sniff_media_type_webp():
    """RIFF....WEBP 头 → 'image/webp'。"""
    from argos_agent.input.attachments import sniff_media_type
    webp = b"RIFF\x00\x00\x00\x00WEBP"
    assert sniff_media_type(webp) == "image/webp"


def test_sniff_media_type_gif():
    """GIF87a / GIF89a 头 → 'image/gif'。"""
    from argos_agent.input.attachments import sniff_media_type
    assert sniff_media_type(b"GIF87a" + b"\x00" * 10) == "image/gif"
    assert sniff_media_type(b"GIF89a" + b"\x00" * 10) == "image/gif"


def test_sniff_media_type_unknown_raises():
    """未知格式 → ValueError(诚实:不静默返回空或假 MIME)。"""
    from argos_agent.input.attachments import sniff_media_type
    with pytest.raises(ValueError, match="unsupported"):
        sniff_media_type(b"\x00\x00\x00\x00")


# ── Task 3: 校验 (validate_attachment) ────────────────────────────────────────

def test_validate_attachment_ok():
    """有效的 PNG(< 5MB)→ validate_attachment 无异常。"""
    from argos_agent.input.attachments import ImageAttachment, validate_attachment
    att = ImageAttachment(data=b"\x89PNG" + b"\x00" * 100,
                          media_type="image/png", source_label="ok.png")
    validate_attachment(att)  # 无异常


def test_validate_attachment_too_large():
    """data > 5MB → ValueError(单张 ≤5MB 上限,对齐 Claude Code)。"""
    from argos_agent.input.attachments import ImageAttachment, validate_attachment
    big = ImageAttachment(data=b"\x00" * (5 * 1024 * 1024 + 1),
                          media_type="image/png", source_label="big.png")
    with pytest.raises(ValueError, match="5MB"):
        validate_attachment(big)


def test_validate_attachment_unsupported_type():
    """不支持的 media_type(如 image/bmp)→ ValueError。"""
    from argos_agent.input.attachments import ImageAttachment, validate_attachment
    att = ImageAttachment(data=b"BM" + b"\x00" * 10,
                          media_type="image/bmp", source_label="x.bmp")
    with pytest.raises(ValueError, match="unsupported|不支持"):
        validate_attachment(att)


# ── Task 4: base64 编码助手 ────────────────────────────────────────────────────

def test_to_base64_returns_str():
    """to_base64(att) → 纯 base64 字符串(无前缀,无换行)。"""
    from argos_agent.input.attachments import ImageAttachment, to_base64
    att = ImageAttachment(data=b"hello", media_type="image/png", source_label="x.png")
    result = to_base64(att)
    assert isinstance(result, str)
    assert result == base64.b64encode(b"hello").decode()


# ── Task 5: 路径检测 (extract_image_paths) ────────────────────────────────────

def test_extract_image_paths_finds_png():
    """prompt 内含 .png 路径 → 提取路径列表。"""
    from argos_agent.input.attachments import extract_image_paths
    text = "请分析这张图 /tmp/screenshot.png 并告诉我结果"
    paths = extract_image_paths(text)
    assert "/tmp/screenshot.png" in paths


def test_extract_image_paths_finds_multiple():
    """多个路径 → 全部提取。"""
    from argos_agent.input.attachments import extract_image_paths
    text = "图1: /a/b.png 图2: /c/d.jpg"
    paths = extract_image_paths(text)
    assert "/a/b.png" in paths
    assert "/c/d.jpg" in paths


def test_extract_image_paths_no_match():
    """无图片路径 → 返回空列表。"""
    from argos_agent.input.attachments import extract_image_paths
    assert extract_image_paths("just some text") == []


def test_extract_image_paths_ignores_non_image():
    """Python 文件路径(.py)不被提取。"""
    from argos_agent.input.attachments import extract_image_paths
    paths = extract_image_paths("look at /some/file.py please")
    assert "/some/file.py" not in paths


# ── Task 6: load_from_path ────────────────────────────────────────────────────

def test_load_from_path_reads_real_file():
    """load_from_path 真实读文件,返回 ImageAttachment(media_type 由嗅探决定)。"""
    from argos_agent.input.attachments import load_from_path
    # 最小合法 PNG (1×1 像素)
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
    """不存在的路径 → FileNotFoundError。"""
    from argos_agent.input.attachments import load_from_path
    with pytest.raises(FileNotFoundError):
        load_from_path("/nonexistent/path/image.png")
