"""daemon 协议:ImageAttachment ↔ JSON-safe wire dict(base64)。

图片字节不进 runs/index.json(只在内存随 worker 传),避免索引膨胀。
畸形条目跳过(诚实降级,不崩整批)。
"""
from __future__ import annotations

import base64

from argos.input.attachments import ImageAttachment


def encode_attachments(atts) -> list[dict]:
    """ImageAttachment 列表 → JSON 可序列化 dict 列表(data base64)。"""
    out: list[dict] = []
    for a in atts or []:
        out.append({
            "data_b64": base64.b64encode(a.data).decode("ascii"),
            "media_type": a.media_type,
            "source_label": a.source_label,
            "width": a.width,
            "height": a.height,
        })
    return out


def decode_attachments(wire) -> list[ImageAttachment]:
    """wire dict 列表 → ImageAttachment 列表。畸形条目跳过(不毁整批)。"""
    out: list[ImageAttachment] = []
    for d in wire or []:
        try:
            out.append(ImageAttachment(
                data=base64.b64decode(d["data_b64"]),
                media_type=d["media_type"],
                source_label=d.get("source_label", "attachment"),
                width=d.get("width"),
                height=d.get("height"),
            ))
        except Exception:  # noqa: BLE001 — 单条畸形不毁整批
            continue
    return out
