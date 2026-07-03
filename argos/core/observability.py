from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, AsyncIterator

from argos.core.recovery import flatten_exception_chain


@dataclass
class StreamDiag:
    started_at: float = field(default_factory=time.monotonic)
    ttfb_s: float | None = None
    chunks: int = 0
    exception_chain: list[str] = field(default_factory=list)


async def stream_diag(source: AsyncIterator[str], diag: StreamDiag) -> AsyncIterator[str]:
    try:
        async for chunk in source:
            if diag.ttfb_s is None:
                diag.ttfb_s = time.monotonic() - diag.started_at
            diag.chunks += 1
            yield chunk
    except BaseException as exc:
        diag.exception_chain = flatten_exception_chain(exc)
        raise


# ── per-step cost ────────────────────────────────────────────────────────
PRICING: dict[str, dict[str, float]] = {
    "MiniMax-M2": {"in": 0.30, "out": 1.20},
    "claude-sonnet-4-6": {"in": 3.00, "out": 15.00},
}


@dataclass(frozen=True, slots=True)
class StepCost:
    tokens_in: int
    tokens_out: int
    cost_usd: float


def cost_of(usage: dict[str, Any] | None, *, model: str) -> StepCost:
    u = usage or {}
    tin = int(u.get("input_tokens", 0) or 0)
    tout = int(u.get("output_tokens", 0) or 0)
    price = PRICING.get(model)
    if price is None:
        return StepCost(tokens_in=tin, tokens_out=tout, cost_usd=0.0)
    cost = (tin * price["in"] + tout * price["out"]) / 1_000_000.0
    return StepCost(tokens_in=tin, tokens_out=tout, cost_usd=cost)
