"""Internal documentation."""
from __future__ import annotations

import random
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ClassifiedError:
    retryable: bool
    should_compress: bool
    should_rotate: bool
    should_fallback: bool
    detail: str


def flatten_exception_chain(exc: BaseException, max_depth: int = 4) -> list[str]:
    """Internal documentation."""
    out: list[str] = []
    cur: BaseException | None = exc
    depth = 0
    while cur is not None and depth < max_depth:
        out.append(f"{type(cur).__name__}: {cur}")
        cur = cur.__cause__ or cur.__context__
        depth += 1
    return out


_CONTEXT_OVERFLOW_MARKERS = (
    "context_length_exceeded", "context length", "too long", "maximum context",
    "prompt is too long", "reduce the length",
)


def _status_of(exc: BaseException) -> int | None:
    """Internal documentation."""
    resp = getattr(exc, "response", None)
    if resp is not None:
        return getattr(resp, "status_code", None)
    return None


def _body_of(exc: BaseException) -> str:
    resp = getattr(exc, "response", None)
    if resp is not None:
        try:
            return resp.text or ""
        except Exception:
            return ""
    return ""


def classify_error(exc: BaseException) -> ClassifiedError:
    chain = flatten_exception_chain(exc)
    detail = " <- ".join(chain)
    text = detail.lower()
    status = _status_of(exc)
    body = _body_of(exc).lower()

    if any(m in text or m in body for m in _CONTEXT_OVERFLOW_MARKERS):
        return ClassifiedError(retryable=True, should_compress=True, should_rotate=False,
                               should_fallback=False, detail=detail)

    if status == 429 or "too many requests" in text or "rate_limit" in text or "rate limit" in text:
        return ClassifiedError(retryable=True, should_compress=False, should_rotate=True,
                               should_fallback=False, detail=detail)

    if status == 401:
        from argos.core.models import CredentialPool
        terminal = CredentialPool.is_terminal_401(401, body)
        return ClassifiedError(retryable=not terminal, should_compress=False, should_rotate=True,
                               should_fallback=False, detail=detail)

    if status in (500, 502, 503, 504):
        return ClassifiedError(retryable=True, should_compress=False, should_rotate=False,
                               should_fallback=False, detail=detail)

    return ClassifiedError(retryable=False, should_compress=False, should_rotate=False,
                           should_fallback=False, detail=detail)


def jittered_backoff(attempt: int, *, base: float = 0.5, cap: float = 30.0) -> float:
    """Internal documentation."""
    ceiling = min(cap, base * (2 ** attempt))
    floor = ceiling / 2.0
    return floor + random.random() * (ceiling - floor)
