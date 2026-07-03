"""Vision capability probing and cache helpers.

Vision and learning caches live under ARGOS_CONFIG_DIR/vision_cache.json,
ARGOS_CONFIG_DIR/learning/candidates, ARGOS_CONFIG_DIR/learning,
ARGOS_CONFIG_DIR/skills/index.json, and ARGOS_CONFIG_DIR/skills.
"""
from __future__ import annotations

import json
import time
from pathlib import Path


class VisionCapabilityCache:
    """Internal documentation."""

    def __init__(self, path: Path | None = None) -> None:
        if path is None:
            from argos import config as C
            cdir = Path(C.get("ARGOS_CONFIG_DIR") or (Path.home() / ".argos")).expanduser()
            path = cdir / "vision_cache.json"
        self._path = path

    def _load(self) -> dict:
        try:
            return json.loads(self._path.read_text()) or {}
        except Exception:  # noqa: BLE001
            return {}

    def get(self, base_url: str, model: str) -> bool | None:
        entry = (self._load().get(base_url) or {}).get(model)
        if isinstance(entry, dict) and isinstance(entry.get("verified"), bool):
            return entry["verified"]
        return None

    def set(self, base_url: str, model: str, verified: bool) -> None:
        data = self._load()
        data.setdefault(base_url, {})[model] = {"verified": verified, "ts": time.time()}
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self._path.write_text(json.dumps(data, indent=2, ensure_ascii=False))
        except Exception:  # noqa: BLE001
            pass


import random
import struct
import zlib

_PROBE_COLORS: dict[str, tuple[int, int, int]] = {
    "red": (255, 0, 0), "green": (0, 200, 0), "blue": (0, 0, 255),
    "yellow": (255, 255, 0), "black": (0, 0, 0), "white": (255, 255, 255),
}
_COLOR_SYNONYMS: dict[str, tuple[str, ...]] = {
    "red": ("red",), "green": ("green",), "blue": ("blue",),
    "yellow": ("yellow",), "black": ("black",), "white": ("white",),
}


def _solid_png(rgb: tuple[int, int, int], w: int = 16, h: int = 16) -> bytes:
    """Internal documentation."""
    def chunk(typ: bytes, data: bytes) -> bytes:
        c = typ + data
        return struct.pack(">I", len(data)) + c + struct.pack(">I", zlib.crc32(c) & 0xFFFFFFFF)
    raw = (b"\x00" + bytes(rgb) * w) * h
    return (b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw))
            + chunk(b"IEND", b""))


class VisionProbe:
    """Internal documentation."""

    def __init__(self, *, color: str | None = None) -> None:
        self._color = color

    async def run(self, model_client) -> bool:
        from argos.input.attachments import ImageAttachment
        color = self._color or random.choice(list(_PROBE_COLORS))
        png = _solid_png(_PROBE_COLORS[color])
        att = ImageAttachment(data=png, media_type="image/png", source_label="vision-probe")
        msgs = [{
            "role": "user",
            "content": "What is the single dominant color of this image? Reply with ONLY the color word.",
            "attachments": [att],
        }]
        try:
            resp = await model_client.complete(msgs, system="You are a vision capability test.")
        except Exception:  # noqa: BLE001
            return False
        low = (resp or "").lower()
        return any(syn in low for syn in _COLOR_SYNONYMS[color])


async def resolve_vision_capability(tier, model_client, cache, *, probe=None) -> bool:
    """Internal documentation."""
    override = getattr(tier, "multimodal", None)
    if override is not None:
        return bool(override)
    cached = cache.get(tier.base_url, tier.model)
    if cached is not None:
        return cached
    verified = await (probe or VisionProbe()).run(model_client)
    cache.set(tier.base_url, tier.model, verified)
    return verified
