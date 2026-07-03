"""Internal documentation."""
from __future__ import annotations

import json
import re
from dataclasses import asdict
from typing import Any

from argos.context.analyzer import ContextBreakdown, ContextBucket


_HEALTH_COLOR = {"green": "green", "yellow": "yellow", "red": "red"}

_MARKUP_RE = re.compile(r"\[/?[a-zA-Z][a-zA-Z0-9 _#]*\]")


def strip_markup(text: str) -> str:
    """Internal documentation."""
    return _MARKUP_RE.sub("", text)


def _method_tag(method: str) -> str:
    """Internal documentation."""
    if method.startswith("api"):
        return "[api]"
    return "[est]"


def _line(name: str, bucket: ContextBucket) -> str:
    """Internal documentation."""
    tag = _method_tag(bucket.method)
    return f"  {name:<20}{bucket.tokens:>7,} tok  {tag:<8}{bucket.source}"


def _detail_line(name: str, tok: int) -> str:
    """Internal documentation."""
    return f"    · {name:<16}{tok:>7,} tok  [est]"


def format_table(b: ContextBreakdown) -> str:
    """Internal documentation."""
    color = _HEALTH_COLOR.get(b.health, "green")
    out: list[str] = []
    out.append("Argos Context Breakdown")
    out.append("─" * 50)
    out.append(_line("system", b.system))
    out.append(_line("memory (4 tier)", b.memory))
    for sub_name, sub_tok in b.memory.details:
        out.append(_detail_line(sub_name, sub_tok))
    out.append(_line(f"tools ({b.tools.entries})", b.tools))
    out.append(_line("messages", b.messages))
    out.append("─" * 50)
    out.append(
        f"[{color}]total {b.total:>7,} tok / {b.window:,} ({b.pct * 100:.1f}%)[/{color}]"
    )
    return "\n".join(out)


def _bucket_dict(b: ContextBucket) -> dict[str, Any]:
    """Internal documentation."""
    d = asdict(b)
    d["details"] = list(b.details)
    return d


def format_table_plain(b: ContextBreakdown) -> str:
    """Internal documentation."""
    return strip_markup(format_table(b))


def format_json(b: ContextBreakdown) -> str:
    """Internal documentation."""
    d: dict[str, Any] = {
        "system": _bucket_dict(b.system),
        "memory": _bucket_dict(b.memory),
        "tools": _bucket_dict(b.tools),
        "messages": _bucket_dict(b.messages),
        "total": b.total,
        "window": b.window,
        "pct": b.pct,
        "health": b.health,
        "method": b.method,
    }
    return json.dumps(d, indent=2, ensure_ascii=False, default=str)
