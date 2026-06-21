"""共享显示格式化助手:成本 / token —— StatusBar 与 ActivityPanel 的单一真源。

此前两个 widget 各自内联复制了成本与 token 缩写逻辑,易随改动漂移。收口到此:
  · fmt_cost:单价未知时返 'N/A'(诚实占位)。绝不再用 '$(N/A)' —— 那形似 shell
    命令替换 $(...),真机里被误读成模板/转义 bug。
  · fmt_tokens / fmt_token_flow:千分缩写 + 'tok' 单位(修"裸数字无单位"观感)。
"""
from __future__ import annotations


def fmt_cost(cost_usd: float | None) -> str:
    """成本显示。已知 → '$0.013';未知(None,模型不在定价表)→ '$N/A'。

    '$N/A' 是全库既有主流形态(tab_strip / eval / cli 一致);此前 StatusBar/ActivityPanel
    误用 '$(N/A)' —— 形似 shell 命令替换 $(...),真机里被误读为模板/转义 bug。统一到 '$N/A'。
    诚实铁律:单价未知不编造 $0.000。
    """
    if cost_usd is None:
        return "$N/A"
    return f"${cost_usd:.3f}"


def fmt_tokens(n: int) -> str:
    """token 千分缩写:≥1000 → '12.4k';否则原整数字串。"""
    if n >= 1000:
        return f"{n / 1000:.1f}k"
    return str(n)


def fmt_token_flow(tokens_in: int, tokens_out: int) -> str:
    """输入/输出 token 流,带方向箭头与单位:'↑12.4k ↓3.1k tok'。

    ↑=输入(发送) ↓=输出(接收);'tok' 单位词消除"这些数字是什么"的歧义。
    """
    return f"↑{fmt_tokens(tokens_in)} ↓{fmt_tokens(tokens_out)} tok"
