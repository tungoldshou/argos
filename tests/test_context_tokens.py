"""#12 Context 可视化:T1 tokens.py 估算(契约 §12;spec §5)。

8 测试覆盖 chars4 / tiktoken / 兜底 / 不崩。"""
from __future__ import annotations

import sys
import types

from argos_agent.context.tokens import token_estimate


def test_estimate_empty_returns_min_one():
    """空串 / None 兜底返 (1, method),防止 0 桶污染 sum。"""
    assert token_estimate("") == (1, "estimate:chars4")
    assert token_estimate(None) == (1, "estimate:chars4")  # type: ignore[arg-type]


def test_estimate_short_text_uses_chars4():
    """11 字符 → 11//4=2,method=chars4。"""
    tok, m = token_estimate("hello world")
    assert tok == 2
    assert m == "estimate:chars4"


def test_estimate_long_text_uses_chars4():
    """1000 字符 → 250。"""
    tok, m = token_estimate("a" * 1000)
    assert tok == 250
    assert m == "estimate:chars4"


def test_estimate_method_explicit_chars4():
    """method 字段必含 'chars4'(可被表格扫到)。"""
    _, m = token_estimate("abc")
    assert "chars4" in m


def test_estimate_uses_tiktoken_if_available(monkeypatch):
    """装了就用 tiktoken:cl100k_base。"""
    fake = types.ModuleType("tiktoken")
    fake_eng = types.SimpleNamespace()
    def _enc(_s: str) -> list[int]:
        return [0] * 7  # 7 token 固定
    fake_eng.encode = _enc
    fake.get_encoding = lambda _n: fake_eng
    monkeypatch.setitem(sys.modules, "tiktoken", fake)
    tok, m = token_estimate("anything")
    assert tok == 7
    assert m == "estimate:tiktoken"


def test_estimate_tiktoken_missing_falls_back(monkeypatch):
    """装但 get_encoding 抛 → 降级 chars4,不崩。"""
    fake = types.ModuleType("tiktoken")
    fake.get_encoding = lambda _n: (_ for _ in ()).throw(RuntimeError("boom"))
    monkeypatch.setitem(sys.modules, "tiktoken", fake)
    tok, m = token_estimate("hello world")
    assert tok == 2
    assert m == "estimate:chars4"


def test_estimate_unicode_chinese():
    """中文字符也走 chars4(不崩,method 标 estimate)。"""
    tok, m = token_estimate("你好世界")  # 4 字符(UTF-8 字节多,但 len 字符=4)
    assert tok == 1  # 4//4=1
    assert "chars4" in m


def test_estimate_never_raises():
    """任何输入都返合法 tuple(spec §13 永不崩)。"""
    for txt in ["", None, "x", "x" * 10_000, "\n\t", "🦊"]:  # type: ignore[arg-type]
        tok, m = token_estimate(txt)  # type: ignore[arg-type]
        assert isinstance(tok, int) and tok >= 1
        assert isinstance(m, str) and m.startswith("estimate:")
