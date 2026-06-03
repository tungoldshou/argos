"""provider 工厂测试:_llm() 按 provider 分发到正确的 LangChain chat 类。"""
import pytest

from argos_agent import config, core


def test_anthropic_provider(monkeypatch):
    monkeypatch.setattr(config, "LLM_PROVIDER", "anthropic")
    monkeypatch.setattr(config, "LLM_KEY", "sk-test")
    monkeypatch.setattr(config, "LLM_MODEL", "MiniMax-M2")
    monkeypatch.setattr(config, "LLM_BASE", "https://api.minimaxi.com/anthropic")
    llm = core._llm()
    assert llm.__class__.__name__ == "ChatAnthropic"


def test_openai_provider(monkeypatch):
    monkeypatch.setattr(config, "LLM_PROVIDER", "openai")
    monkeypatch.setattr(config, "LLM_KEY", "sk-test")
    monkeypatch.setattr(config, "LLM_MODEL", "gpt-4o-mini")
    monkeypatch.setattr(config, "LLM_BASE", "https://api.openai.com/v1")
    llm = core._llm()
    assert llm.__class__.__name__ == "ChatOpenAI"


def test_missing_key_raises(monkeypatch):
    monkeypatch.setattr(config, "LLM_KEY", None)
    with pytest.raises(RuntimeError):
        core._llm()
