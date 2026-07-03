from __future__ import annotations

import sys
import types

import pytest

from argos.context.tokens import token_estimate


@pytest.fixture
def no_tiktoken(monkeypatch):
    monkeypatch.setitem(sys.modules, "tiktoken", None)


def test_estimate_empty_returns_min_one():
    assert token_estimate("")[0] == 1
    assert token_estimate(None)[0] == 1  # type: ignore[arg-type]


def test_estimate_short_text_uses_chars4(no_tiktoken):
    tok, m = token_estimate("hello world")
    assert tok == 2
    assert m == "estimate:chars4"


def test_estimate_long_text_uses_chars4(no_tiktoken):
    tok, m = token_estimate("a" * 1000)
    assert tok == 250
    assert m == "estimate:chars4"


def test_estimate_method_explicit_chars4(no_tiktoken):
    _, m = token_estimate("abc")
    assert "chars4" in m


def test_estimate_uses_tiktoken_if_available(monkeypatch):
    fake = types.ModuleType("tiktoken")
    fake_eng = types.SimpleNamespace()
    def _enc(_s: str) -> list[int]:
        return [0] * 7
    fake_eng.encode = _enc
    fake.get_encoding = lambda _n: fake_eng
    monkeypatch.setitem(sys.modules, "tiktoken", fake)
    tok, m = token_estimate("anything")
    assert tok == 7
    assert m == "estimate:tiktoken"


def test_estimate_tiktoken_missing_falls_back(monkeypatch):
    fake = types.ModuleType("tiktoken")
    fake.get_encoding = lambda _n: (_ for _ in ()).throw(RuntimeError("boom"))
    monkeypatch.setitem(sys.modules, "tiktoken", fake)
    tok, m = token_estimate("hello world")
    assert tok == 2
    assert m == "estimate:chars4"


def test_estimate_unicode_chinese(no_tiktoken):
    tok, m = token_estimate("你好世界")
    assert tok == 1  # 4//4=1
    assert "chars4" in m


def test_estimate_never_raises():
    for txt in ["", None, "x", "x" * 10_000, "\n\t", "🦊"]:  # type: ignore[arg-type]
        tok, m = token_estimate(txt)  # type: ignore[arg-type]
        assert isinstance(tok, int) and tok >= 1
        assert isinstance(m, str) and m.startswith("estimate:")
