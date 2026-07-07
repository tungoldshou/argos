from __future__ import annotations

import base64
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from argos.i18n import t

SUPPORTED_MEDIA_TYPES: frozenset[str] = frozenset({
    "image/png",
    "image/jpeg",
    "image/webp",
    "image/gif",
})

MAX_SIZE_BYTES: int = 10 * 1024 * 1024

_IMAGE_PATH_RE = re.compile(
    r'(?:^|(?<=\s)|(?<=\())(/[^\s\)\'\"]+\.(?:png|jpg|jpeg|webp|gif))',
    re.IGNORECASE,
)


@dataclass(frozen=True)
class ImageAttachment:
    data: bytes
    media_type: str
    source_label: str
    width: Optional[int] = None
    height: Optional[int] = None


def sniff_media_type(data: bytes) -> str:
    if data[:8] == b"\x89PNG\r\n\x1a\n" or data[:4] == b"\x89PNG":
        return "image/png"
    if data[:2] == b"\xff\xd8":
        return "image/jpeg"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif"
    preview = data[:8].hex()
    raise ValueError(f"unsupported image format: header bytes={preview!r}")


def validate_attachment(att: ImageAttachment) -> None:
    if att.media_type not in SUPPORTED_MEDIA_TYPES:
        raise ValueError(
            t("core2.attachments.unsupported_format",
              media_type=att.media_type, supported=sorted(SUPPORTED_MEDIA_TYPES))
        )
    if len(att.data) > MAX_SIZE_BYTES:
        raise ValueError(
            t("core2.attachments.too_large", size=len(att.data) / 1024 / 1024)
        )


def _sips_reencode(
    att: ImageAttachment, *, fmt: str, media_type: str,
) -> ImageAttachment | None:
    if sys.platform != "darwin" or shutil.which("sips") is None:
        return None
    out_suffix = ".jpg" if fmt == "jpeg" else ".png"
    try:
        with tempfile.TemporaryDirectory() as td:
            in_path = Path(td) / "input.png"
            out_path = Path(td) / f"output{out_suffix}"
            in_path.write_bytes(att.data)
            cmd = ["sips", "-s", "format", fmt]
            if fmt == "jpeg":
                cmd.extend(["-s", "formatOptions", "95"])
            cmd.extend([str(in_path), "--out", str(out_path)])
            proc = subprocess.run(cmd, capture_output=True, timeout=30)
            if proc.returncode != 0 or not out_path.exists():
                return None
            data = out_path.read_bytes()
    except (OSError, subprocess.SubprocessError):
        return None
    if not data:
        return None
    return ImageAttachment(
        data=data,
        media_type=media_type,
        source_label=att.source_label,
        width=att.width,
        height=att.height,
    )


def prepare_attachment(att: ImageAttachment) -> ImageAttachment:
    if att.media_type not in SUPPORTED_MEDIA_TYPES:
        validate_attachment(att)
        return att
    if len(att.data) <= MAX_SIZE_BYTES:
        validate_attachment(att)
        return att
    if att.media_type == "image/png":
        png = _sips_reencode(att, fmt="png", media_type="image/png")
        if (
            png is not None
            and len(png.data) < len(att.data)
            and len(png.data) <= MAX_SIZE_BYTES
        ):
            validate_attachment(png)
            return png
        jpeg = _sips_reencode(att, fmt="jpeg", media_type="image/jpeg")
        if jpeg is not None and len(jpeg.data) <= MAX_SIZE_BYTES:
            validate_attachment(jpeg)
            return jpeg
    validate_attachment(att)
    return att


def to_base64(att: ImageAttachment) -> str:
    return base64.b64encode(att.data).decode("ascii")


def extract_image_paths(text: str) -> list[str]:
    matches = _IMAGE_PATH_RE.findall(text)
    seen: set[str] = set()
    result: list[str] = []
    for m in matches:
        if m not in seen:
            seen.add(m)
            result.append(m)
    return result


def load_from_path(path: str) -> ImageAttachment:
    import os
    with open(path, "rb") as f:
        data = f.read()
    media_type = sniff_media_type(data)
    return prepare_attachment(ImageAttachment(
        data=data,
        media_type=media_type,
        source_label=os.path.basename(path),
    ))
