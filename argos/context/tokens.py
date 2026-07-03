"""Internal documentation."""
from __future__ import annotations


def token_estimate(text: str | None) -> tuple[int, str]:
    """Internal documentation."""
    txt = text or ""
    try:
        import tiktoken  # type: ignore[import-not-found]
        enc = tiktoken.get_encoding("cl100k_base")
        return max(1, len(enc.encode(txt))), "estimate:tiktoken"
    except Exception:  # noqa: BLE001
        return max(1, len(txt) // 4), "estimate:chars4"
