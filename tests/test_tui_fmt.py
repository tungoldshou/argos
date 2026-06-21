"""共享显示格式化助手测试(argos.tui.widgets._fmt)。

修右侧面板/底栏两处问题:
  1. 成本未知曾渲染成 '$(N/A)' —— 形似 shell 命令替换 $(...),易被误读为模板/转义 bug。
     改为诚实中性的 'N/A'(不带 $,不带括号)。
  2. token 计数曾是裸数字(↑37.9k ↓174),无单位。加 'tok' 单位词。
StatusBar 与 ActivityPanel 此前各自复制了成本/token 格式化逻辑 —— 收口到单一真源。
"""
from __future__ import annotations

from argos.tui.widgets._fmt import fmt_cost, fmt_tokens, fmt_token_flow


# ── fmt_cost:成本未知不再用 shell 样的 $(N/A) ──────────────────────────────
def test_fmt_cost_known_keeps_dollar_and_three_decimals():
    assert fmt_cost(0.013) == "$0.013"
    assert fmt_cost(0.0) == "$0.000"


def test_fmt_cost_unknown_uses_dollar_na_not_shell_form():
    """单价未知 → '$N/A'(全库既有主流形态);绝不再产出 '$(N/A)'(像 shell $())。"""
    assert fmt_cost(None) == "$N/A"
    assert "$(" not in fmt_cost(None)


# ── fmt_tokens:千分缩写(与既有 _fmt_tokens 行为一致)────────────────────────
def test_fmt_tokens_below_1000_raw():
    assert fmt_tokens(0) == "0"
    assert fmt_tokens(174) == "174"
    assert fmt_tokens(999) == "999"


def test_fmt_tokens_at_and_above_1000_abbreviated():
    assert fmt_tokens(1000) == "1.0k"
    assert fmt_tokens(12400) == "12.4k"
    assert fmt_tokens(37900) == "37.9k"


# ── fmt_token_flow:带方向箭头 + 单位 ─────────────────────────────────────
def test_fmt_token_flow_has_arrows_and_unit():
    """↑输入 ↓输出 + 'tok' 单位 —— 修"裸数字无单位"。"""
    out = fmt_token_flow(37900, 174)
    assert out == "↑37.9k ↓174 tok"
    assert "tok" in out
    assert out.startswith("↑")
