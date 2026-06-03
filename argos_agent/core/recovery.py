"""恢复层(契约 §7;spec §3.3 L4):error_classifier + jittered backoff + 死循环兜底。

cascade 不变量(spec §12.2):should_fallback 升级到 premium 由【外部判据】(反复 verify 失败)
决定,classify_error 仅在"反复 transient 失败耗尽 key"这类外部信号下置 should_fallback,
绝不读模型自报 confidence。
"""
from __future__ import annotations

import random
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ClassifiedError:
    retryable: bool
    should_compress: bool   # 上下文超限 → 触发 compaction
    should_rotate: bool     # 限流/transient/terminal 401 → 轮换 credential_pool
    should_fallback: bool   # 反复失败 → cascade 升级 premium(由外部判据,非模型 confidence)
    detail: str             # 挖到的真因(剥异常链)


def flatten_exception_chain(exc: BaseException, max_depth: int = 4) -> list[str]:
    """拍平异常链(spec §3.3 L5:挖到 4 层真因)。沿 __cause__/__context__ 走。"""
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
    """从 httpx.HTTPStatusError 抽 status_code,否则 None。"""
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

    # 上下文超限(可能是 ValueError / provider 400)→ 压缩后重试
    if any(m in text or m in body for m in _CONTEXT_OVERFLOW_MARKERS):
        return ClassifiedError(retryable=True, should_compress=True, should_rotate=False,
                               should_fallback=False, detail=detail)

    # 429 限流 → rotate + retry
    if status == 429 or "too many requests" in text or "rate_limit" in text or "rate limit" in text:
        return ClassifiedError(retryable=True, should_compress=False, should_rotate=True,
                               should_fallback=False, detail=detail)

    # 401:terminal(无效 key)不可重试同 key,但应 rotate 换 key;transient(限流伪装)可重试
    if status == 401:
        from argos_agent.core.models import CredentialPool
        terminal = CredentialPool.is_terminal_401(401, body)
        return ClassifiedError(retryable=not terminal, should_compress=False, should_rotate=True,
                               should_fallback=False, detail=detail)

    # 5xx transient → retry(不 rotate:服务端问题,换 key 无用)
    if status in (500, 502, 503, 504):
        return ClassifiedError(retryable=True, should_compress=False, should_rotate=False,
                               should_fallback=False, detail=detail)

    # 未知 → 不可重试、不升级(诚实:不瞎重试制造死循环)
    return ClassifiedError(retryable=False, should_compress=False, should_rotate=False,
                           should_fallback=False, detail=detail)


def jittered_backoff(attempt: int, *, base: float = 0.5, cap: float = 30.0) -> float:
    """指数退避 + full jitter(spec §3.3 L4)。attempt 从 0 起。
    下界随 attempt 单调递增(用 base*2^attempt 的一半做下界保证),上界 cap 封顶。"""
    ceiling = min(cap, base * (2 ** attempt))
    floor = ceiling / 2.0
    return floor + random.random() * (ceiling - floor)
