from __future__ import annotations

from argos.tui.widgets._fmt import fmt_cost, fmt_tokens, fmt_token_flow


def test_fmt_cost_known_keeps_dollar_and_three_decimals():
    assert fmt_cost(0.013) == "$0.013"
    assert fmt_cost(0.0) == "$0.000"


def test_fmt_cost_unknown_uses_dollar_na_not_shell_form():
    assert fmt_cost(None) == "$N/A"
    assert "$(" not in fmt_cost(None)


def test_fmt_tokens_below_1000_raw():
    assert fmt_tokens(0) == "0"
    assert fmt_tokens(174) == "174"
    assert fmt_tokens(999) == "999"


def test_fmt_tokens_at_and_above_1000_abbreviated():
    assert fmt_tokens(1000) == "1.0k"
    assert fmt_tokens(12400) == "12.4k"
    assert fmt_tokens(37900) == "37.9k"


def test_fmt_token_flow_has_arrows_and_unit():
    out = fmt_token_flow(37900, 174)
    assert out == "↑37.9k ↓174 tok"
    assert "tok" in out
    assert out.startswith("↑")
