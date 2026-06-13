"""#12 Context 可视化:token 估算(契约 §12;spec §5)。

混合策略:API 报的真值走 method=api;非对话侧(system / memory / tools)走 chars4
兜底,可选 tiktoken 升级(cl100k_base ≈ Anthropic/OpenAI tokenizer 近似)。
返回 (tokens, method),method ∈ {estimate:chars4, estimate:tiktoken},永不抛(spec §13)。"""
from __future__ import annotations


def token_estimate(text: str | None) -> tuple[int, str]:
    """若装了 tiktoken → 优先 cl100k_base;否则降级 chars4(len // 4)。
    永远返 (>=1, "estimate:..."),空串也返 1 token(spec §5 误差诚实:min 1 防 0 污染 sum)。"""
    txt = text or ""
    try:
        import tiktoken  # type: ignore[import-not-found]
        enc = tiktoken.get_encoding("cl100k_base")
        # min-1 不变量:tiktoken 对空串 encode()=0,必须 floor 成 1(与 chars4 分支一致),
        # 否则 0 token 桶污染 sum(spec §5 误差诚实)。
        return max(1, len(enc.encode(txt))), "estimate:tiktoken"
    except Exception:  # noqa: BLE001 — 没装/版本不兼容/任何异常都降级(spec D1 + §13)
        return max(1, len(txt) // 4), "estimate:chars4"
