from __future__ import annotations


def fmt_cost(cost_usd: float | None) -> str:
    if cost_usd is None:
        return "$N/A"
    return f"${cost_usd:.3f}"


def fmt_tokens(n: int) -> str:
    if n >= 1000:
        return f"{n / 1000:.1f}k"
    return str(n)


def fmt_token_flow(tokens_in: int, tokens_out: int) -> str:
    return f"↑{fmt_tokens(tokens_in)} ↓{fmt_tokens(tokens_out)} tok"
