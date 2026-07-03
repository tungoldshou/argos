from __future__ import annotations

import base64
import re
from dataclasses import dataclass, field
from typing import Optional

from argos.i18n import t

SUPPORTED_MEDIA_TYPES: frozenset[str] = frozenset({
    "image/png",
    "image/jpeg",
    "image/webp",
    "image/gif",
})

MAX_SIZE_BYTES: int = 5 * 1024 * 1024

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
    return ImageAttachment(
        data=data,
        media_type=media_type,
        source_label=os.path.basename(path),
    )
