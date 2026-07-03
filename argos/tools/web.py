"""Internal documentation."""
from __future__ import annotations

from argos import web
from argos.i18n import t

_EXTRACT_COMPRESS_THRESHOLD = 6000
_SNIPPET_MAX = 300


def web_search(query: str, limit: int = 5) -> str:
    """Internal documentation."""
    res = web.search(query, limit)
    if not res.get("success"):
        return t("tools.web.search_failed", error=res.get("error") or t("tools.web.unknown_error"))
    results = res.get("results") or []
    if not results:
        return t("tools.web.search_no_results")
    lines = []
    for i, r in enumerate(results, 1):
        snippet = " ".join(str(r.get("snippet") or "").split())
        if len(snippet) > _SNIPPET_MAX:
            snippet = snippet[:_SNIPPET_MAX] + "…"
        lines.append(f"{i}. {r.get('title', '')}\n   {r.get('url', '')}\n   {snippet}")
    return "\n".join(lines)


def web_extract(url: str) -> str:
    """Internal documentation."""
    res = web.extract(url)
    if not res.get("success"):
        return t("tools.web.extract_failed", error=res.get("error") or t("tools.web.unknown_error"))
    text = res.get("text") or ""
    if len(text) <= _EXTRACT_COMPRESS_THRESHOLD:
        return text or t("tools.web.extract_empty")
    return text[:8000] + t("tools.web.extract_truncated", total=len(text))


def host_for(action: str, args: dict) -> str:
    """Internal documentation."""
    if action == "web_extract":
        return args.get("url", "")
    if action == "web_search":
        return web.active_search_host()
    return ""


def extract_url_blocked(url: str) -> bool:
    """Internal documentation."""
    from urllib.parse import urlparse
    u = url if "://" in (url or "") else f"http://{url}"
    host = (urlparse(u).hostname or "").strip()
    if not host:
        return True
    return web._is_blocked_host(host)
