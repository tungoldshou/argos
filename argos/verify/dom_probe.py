from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from argos.i18n import is_error_result, t

if TYPE_CHECKING:
    from argos.browser import BrowserController

_TEXT_EXCERPT_MAX = 200


@dataclass(frozen=True, slots=True)
class DomProbeResult:
    found: bool = False
    text_excerpt: str = ""
    error: str = ""


class DomProber:

    def __init__(self, browser: "BrowserController | None") -> None:
        self._browser = browser


    def probe(
        self,
        url: str | None,
        selector: str,
        *,
        expected_text: str | None = None,
        timeout_s: float = 15.0,
    ) -> DomProbeResult:
        if self._browser is None:
            return DomProbeResult(
                found=False, text_excerpt="",
                error=t("verify.dom_probe.no_browser"),
            )
        try:
            return self._do_probe(url, selector, expected_text=expected_text)
        except Exception as exc:  # noqa: BLE001
            return DomProbeResult(
                found=False, text_excerpt="",
                error=t("verify.dom_probe.exception", exc_type=type(exc).__name__, exc=exc),
            )


    def _do_probe(
        self,
        url: str | None,
        selector: str,
        *,
        expected_text: str | None,
    ) -> DomProbeResult:
        browser = self._browser
        assert browser is not None

        if url:
            nav_result = browser.navigate(url)
            if is_error_result(nav_result):
                return DomProbeResult(
                    found=False, text_excerpt="",
                    error=t("verify.dom_probe.nav_failed", result=nav_result),
                )

        snapshot = browser.snapshot(max_chars=8000)
        if is_error_result(snapshot):
            return DomProbeResult(
                found=False, text_excerpt="",
                error=t("verify.dom_probe.snapshot_failed", result=snapshot),
            )

        #
        #
        body_text = _extract_body_text(snapshot)

        if expected_text is not None:
            if expected_text.lower() in body_text.lower():
                excerpt = _excerpt_around(body_text, expected_text)
                return DomProbeResult(found=True, text_excerpt=excerpt, error="")
            else:
                return DomProbeResult(
                    found=False,
                    text_excerpt="",
                    error="",
                )
        else:
            selector_text = _selector_to_text_hint(selector)
            detail = t(
                "verify.dom_probe.weak_evidence",
                selector=selector,
                hint=selector_text,
            )
            return DomProbeResult(found=False, text_excerpt="", error=detail)



_SELECTOR_CLEAN_RE = re.compile(r'[.#>\[\]:+~*=()\s]+')
_PSEUDO_RE = re.compile(r':[a-z-]+(\([^)]*\))?', re.I)


def _selector_to_text_hint(selector: str) -> str:
    cleaned = _PSEUDO_RE.sub(' ', selector)
    parts = _SELECTOR_CLEAN_RE.split(cleaned)
    meaningful = [p for p in parts if p and len(p) > 1]
    return meaningful[-1] if meaningful else selector.strip().lstrip('.#')


def _extract_body_text(snapshot: str) -> str:
    from argos.i18n import t as _t
    _hdr = _t("browser.snapshot_header").split("\n", 1)[0]
    _page_marker = _hdr.split("{", 1)[0].strip() or "[Page]"
    lines = snapshot.split('\n')
    body_lines = []
    for line in lines:
        if line.startswith(_page_marker) or line.startswith('[URL]'):
            continue
        body_lines.append(line)
    return '\n'.join(body_lines).strip()


def _excerpt_around(text: str, keyword: str, window: int = _TEXT_EXCERPT_MAX) -> str:
    idx = text.find(keyword)
    if idx < 0:
        return text[:window]
    start = max(0, idx - window // 2)
    end = min(len(text), idx + len(keyword) + window // 2)
    excerpt = text[start:end]
    if start > 0:
        excerpt = "…" + excerpt
    if end < len(text):
        excerpt = excerpt + "…"
    return excerpt
