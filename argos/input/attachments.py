"""attachments.py — ImageAttachment dataclass + 路径检测 + 校验 + media_type 嗅探 + base64(spec §4、§5)。

本模块纯逻辑、无网络 I/O，易测。
图片只在协议适配器 payload() 一处物化成 wire 格式；此处仅做数据封装与校验。

诚实边界：
  - 未知 media_type → ValueError("unsupported image format …")，绝不静默返回假 MIME。
  - 体积超 5MB → ValueError，不截断、不静默剥除。
  - 不支持的格式(bmp 等)→ ValueError。
  - 文件不存在 → FileNotFoundError(由 open() 原生抛出)。
"""
from __future__ import annotations

import base64
import re
from dataclasses import dataclass, field
from typing import Optional

# 支持的 media_type 白名单(对齐 Anthropic Claude Code §4)
SUPPORTED_MEDIA_TYPES: frozenset[str] = frozenset({
    "image/png",
    "image/jpeg",
    "image/webp",
    "image/gif",
})

# 单张体积上限 5MB(对齐 Claude Code)
MAX_SIZE_BYTES: int = 5 * 1024 * 1024

# 图片路径检测正则：匹配以 .png/.jpg/.jpeg/.webp/.gif 结尾的绝对或相对路径
_IMAGE_PATH_RE = re.compile(
    r'(?:^|(?<=\s)|(?<=\())(/[^\s\)\'\"]+\.(?:png|jpg|jpeg|webp|gif))',
    re.IGNORECASE,
)


@dataclass(frozen=True)
class ImageAttachment:
    """图片附件(方案 C 边车字段)。

    Attributes:
        data:         原始字节内容
        media_type:   MIME 类型，需在 SUPPORTED_MEDIA_TYPES 白名单内
        source_label: 来源描述(文件名 / "clipboard" / URL 等)，用于诚实展示
        width:        像素宽度(可选元数据)
        height:       像素高度(可选元数据)
    """
    data: bytes
    media_type: str
    source_label: str
    width: Optional[int] = None
    height: Optional[int] = None


def sniff_media_type(data: bytes) -> str:
    """通过字节头魔数嗅探 media_type。

    支持：PNG / JPEG / WebP / GIF。
    未知格式 → ValueError("unsupported image format: …")。
    """
    if data[:8] == b"\x89PNG\r\n\x1a\n" or data[:4] == b"\x89PNG":
        return "image/png"
    if data[:2] == b"\xff\xd8":
        return "image/jpeg"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif"
    # 诚实：未知格式，不静默返回
    preview = data[:8].hex()
    raise ValueError(f"unsupported image format: header bytes={preview!r}")


def validate_attachment(att: ImageAttachment) -> None:
    """校验 ImageAttachment 合法性。

    失败条件（诚实门禁）：
      - media_type 不在支持白名单 → ValueError("unsupported …")
      - data 体积 > 5MB → ValueError("5MB …")
    """
    if att.media_type not in SUPPORTED_MEDIA_TYPES:
        raise ValueError(
            f"unsupported / 不支持的图片格式: {att.media_type!r}。"
            f"支持的格式: {sorted(SUPPORTED_MEDIA_TYPES)}"
        )
    if len(att.data) > MAX_SIZE_BYTES:
        raise ValueError(
            f"图片超过 5MB 上限 (actual={len(att.data) / 1024 / 1024:.1f}MB)。"
            "请压缩或裁剪后重试。"
        )


def to_base64(att: ImageAttachment) -> str:
    """将 ImageAttachment.data 编码为纯 base64 字符串（无前缀，无换行）。

    协议适配器在 payload() 中调用，将字节序列化为 wire 格式。
    """
    return base64.b64encode(att.data).decode("ascii")


def extract_image_paths(text: str) -> list[str]:
    """从 prompt 文本中提取图片文件路径。

    匹配以 .png/.jpg/.jpeg/.webp/.gif 结尾的绝对路径（以 / 开头）。
    返回去重后的路径列表（保持原顺序）。
    """
    matches = _IMAGE_PATH_RE.findall(text)
    # 去重保序
    seen: set[str] = set()
    result: list[str] = []
    for m in matches:
        if m not in seen:
            seen.add(m)
            result.append(m)
    return result


def load_from_path(path: str) -> ImageAttachment:
    """从文件路径读取图片，返回 ImageAttachment。

    media_type 由 sniff_media_type() 嗅探决定。
    文件不存在 → FileNotFoundError（由 open() 原生抛出）。
    未知格式 → ValueError（由 sniff_media_type 抛出）。
    """
    import os
    with open(path, "rb") as f:
        data = f.read()
    media_type = sniff_media_type(data)
    return ImageAttachment(
        data=data,
        media_type=media_type,
        source_label=os.path.basename(path),
    )
