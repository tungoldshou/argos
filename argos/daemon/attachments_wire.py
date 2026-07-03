from __future__ import annotations

import base64

from argos.input.attachments import ImageAttachment


def encode_attachments(atts) -> list[dict]:
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
        except Exception:  # noqa: BLE001
            continue
    return out
