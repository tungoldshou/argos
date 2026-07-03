from __future__ import annotations

from typing import Optional

from argos.skills_runtime.builtin.security_review.secrets import (  # noqa: F401
    SECRET_PATTERNS,
    _SecretPattern,  # type: ignore
)

MAX_SCAN_BYTES: int = 1_000_000


def find_secret_in_content(content: str) -> Optional[str]:
    if not isinstance(content, str):
        return None
    if len(content.encode("utf-8")) > MAX_SCAN_BYTES:
        return None
    for pat in SECRET_PATTERNS:
        if pat.name == ".env file committed":
            continue
        if pat.regex.search(content):
            return pat.name
    return None
