"""可观测层 L5(契约 §1 CostUpdate;spec §3.3 L5)。

stream_diag:包流式生成器,测 TTFB(首 chunk 墙钟)/chunk 数/异常链拍平(挖 4 层真因 —— 现顶层
except 把 provider 错误链丢了,这里捞回)。
per-step cost:按 usage_metadata 的 input_tokens/output_tokens(沿用 cost_ab.py 抽法) × PRICING 表
算 per-step 成本。未知模型不瞎编价(成本算 0,token 仍如实计 —— 诚实)。
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, AsyncIterator

from argos_agent.core.recovery import flatten_exception_chain


@dataclass
class StreamDiag:
    """单次流的诊断快照(可变累积器,run 中边走边填)。"""
    started_at: float = field(default_factory=time.monotonic)
    ttfb_s: float | None = None           # 首 chunk 到达的相对秒
    chunks: int = 0
    exception_chain: list[str] = field(default_factory=list)


async def stream_diag(source: AsyncIterator[str], diag: StreamDiag) -> AsyncIterator[str]:
    """透传 source 的每个 chunk,同时填 diag。异常时拍平异常链(4 层真因)再抛。"""
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
# 价格单位:USD / 1M tokens。诚实:只列实际接的模型,未知模型不编价。
# 数值为占位基线(spec §13:beta 期实测校准);改价不影响逻辑,只改这张表。
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
    """从 usage_metadata 算单步成本。usage 形如 {"input_tokens": N, "output_tokens": M}。
    未知模型 → cost_usd=0.0(不瞎编价),token 仍如实计。"""
    u = usage or {}
    tin = int(u.get("input_tokens", 0) or 0)
    tout = int(u.get("output_tokens", 0) or 0)
    price = PRICING.get(model)
    if price is None:
        return StepCost(tokens_in=tin, tokens_out=tout, cost_usd=0.0)
    cost = (tin * price["in"] + tout * price["out"]) / 1_000_000.0
    return StepCost(tokens_in=tin, tokens_out=tout, cost_usd=cost)
