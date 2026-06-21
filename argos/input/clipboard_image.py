"""读系统剪贴板里的图片 → ImageAttachment(宿主进程,沙箱外)。

诚实边界:无工具 / 剪贴板无图 / 内容非图 / 平台不支持 → ClipboardError(带可操作提示),绝不静默。
macOS:pngpaste(brew install pngpaste);Linux:xclip。Windows 本期不支持(诚实报)。

注:attachments.sniff_media_type / validate_attachment 用 ValueError 表达非法(非返回 None),
本模块把它们翻译成 ClipboardError,给剪贴板场景一致的诚实错误类型。
"""
from __future__ import annotations

import shutil
import subprocess
import sys

from argos.i18n import t
from argos.input.attachments import (
    ImageAttachment, sniff_media_type, validate_attachment,
)


class ClipboardError(Exception):
    """读剪贴板图片失败:无工具 / 无图 / 内容非图 / 平台不支持。"""


def _read_bytes() -> bytes:
    """按平台调外部工具,把剪贴板图片以 PNG 字节读出。失败抛 ClipboardError。"""
    if sys.platform == "darwin":
        if shutil.which("pngpaste") is None:
            raise ClipboardError(t("input.clipboard.need_pngpaste"))
        proc = subprocess.run(["pngpaste", "-"], capture_output=True, timeout=10)
        if proc.returncode != 0 or not proc.stdout:
            raise ClipboardError(t("input.clipboard.no_image_macos"))
        return proc.stdout
    if sys.platform.startswith("linux"):
        if shutil.which("xclip") is None:
            raise ClipboardError(t("input.clipboard.need_xclip"))
        proc = subprocess.run(
            ["xclip", "-selection", "clipboard", "-t", "image/png", "-o"],
            capture_output=True, timeout=10,
        )
        if proc.returncode != 0 or not proc.stdout:
            raise ClipboardError(t("input.clipboard.no_image_linux"))
        return proc.stdout
    raise ClipboardError(t("input.clipboard.unsupported_platform", platform=sys.platform))


def read_clipboard_image() -> ImageAttachment:
    """读剪贴板图片 → 嗅探/校验 → ImageAttachment(source_label='clipboard')。
    内容非受支持图片格式 / 超 5MB → 诚实 ClipboardError(翻译自 attachments 的 ValueError)。"""
    data = _read_bytes()
    try:
        media = sniff_media_type(data)
    except ValueError as e:
        raise ClipboardError(t("input.clipboard.bad_format")) from e
    att = ImageAttachment(data=data, media_type=media, source_label="clipboard")
    try:
        validate_attachment(att)  # 复用 Plan 1 的体积/类型校验(超 5MB → ValueError)
    except ValueError as e:
        raise ClipboardError(str(e)) from e
    return att
