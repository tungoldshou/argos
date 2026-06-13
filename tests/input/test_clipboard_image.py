"""clipboard_image.py — 读系统剪贴板图片(mac pngpaste / linux xclip),诚实错误。"""
import subprocess
import pytest
from argos.input import clipboard_image as ci
from argos.input.clipboard_image import ClipboardError
from argos.input.attachments import ImageAttachment

_PNG = b"\x89PNG\r\n\x1a\n\x00\x00\x00\x0dIHDR" + b"\x00\x00\x00\x0a\x00\x00\x00\x0a" + b"\x00" * 5


def test_reads_png_on_macos(monkeypatch):
    monkeypatch.setattr(ci.sys, "platform", "darwin")
    monkeypatch.setattr(ci.shutil, "which", lambda name: "/usr/local/bin/pngpaste")

    def fake_run(cmd, **kw):
        return subprocess.CompletedProcess(cmd, 0, stdout=_PNG, stderr=b"")
    monkeypatch.setattr(ci.subprocess, "run", fake_run)

    att = ci.read_clipboard_image()
    assert isinstance(att, ImageAttachment)
    assert att.media_type == "image/png"
    assert att.source_label == "clipboard"


def test_missing_tool_is_honest(monkeypatch):
    monkeypatch.setattr(ci.sys, "platform", "darwin")
    monkeypatch.setattr(ci.shutil, "which", lambda name: None)
    with pytest.raises(ClipboardError) as e:
        ci.read_clipboard_image()
    assert "pngpaste" in str(e.value)


def test_empty_clipboard_is_honest(monkeypatch):
    monkeypatch.setattr(ci.sys, "platform", "darwin")
    monkeypatch.setattr(ci.shutil, "which", lambda name: "/x/pngpaste")
    monkeypatch.setattr(ci.subprocess, "run",
                        lambda cmd, **kw: subprocess.CompletedProcess(cmd, 1, b"", b"no image"))
    with pytest.raises(ClipboardError):
        ci.read_clipboard_image()


def test_unsupported_clipboard_content_is_honest(monkeypatch):
    """剪贴板有内容但不是图片 → sniff_media_type 抛 ValueError → 诚实 ClipboardError。"""
    monkeypatch.setattr(ci.sys, "platform", "darwin")
    monkeypatch.setattr(ci.shutil, "which", lambda name: "/x/pngpaste")
    monkeypatch.setattr(ci.subprocess, "run",
                        lambda cmd, **kw: subprocess.CompletedProcess(cmd, 0, b"not an image", b""))
    with pytest.raises(ClipboardError):
        ci.read_clipboard_image()


def test_unsupported_platform_is_honest(monkeypatch):
    monkeypatch.setattr(ci.sys, "platform", "win32")
    with pytest.raises(ClipboardError) as e:
        ci.read_clipboard_image()
    assert "win32" in str(e.value) or "不支持" in str(e.value)
