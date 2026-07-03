from __future__ import annotations

import shutil
import subprocess
import sys

from argos.i18n import t
from argos.input.attachments import (
    ImageAttachment, sniff_media_type, validate_attachment,
)


class ClipboardError(Exception):
    pass


def _read_bytes() -> bytes:
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
    data = _read_bytes()
    try:
        media = sniff_media_type(data)
    except ValueError as e:
        raise ClipboardError(t("input.clipboard.bad_format")) from e
    att = ImageAttachment(data=data, media_type=media, source_label="clipboard")
    try:
        validate_attachment(att)
    except ValueError as e:
        raise ClipboardError(str(e)) from e
    return att
