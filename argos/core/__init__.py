"""Internal documentation."""
from __future__ import annotations

from typing import Any

from argos.core.honesty import HONESTY_SYSTEM  # noqa: F401


def final_text(message: Any) -> str:
    """Internal documentation."""
    c = getattr(message, "content", message)
    if isinstance(c, str):
        return c
    if isinstance(c, list):
        parts = [b.get("text", "") for b in c if isinstance(b, dict) and b.get("type") == "text"]
        return "".join(parts)
    return str(c)


def text_delta(chunk: Any) -> str:
    """Internal documentation."""
    c = getattr(chunk, "content", "")
    if isinstance(c, str):
        return c
    if isinstance(c, list):
        return "".join(b.get("text", "") for b in c if isinstance(b, dict) and b.get("type") == "text")
    return ""
