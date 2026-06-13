"""web.py 测试:provider 选择 + 归一化 + extract 兜底。走网部分全 mock,不依赖外网。"""
import pytest

from argos import web


def test_search_uses_ddgs_when_no_tavily_key(monkeypatch):
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)
    called = {}
    def fake_ddgs(query, limit):
        called["ddgs"] = (query, limit)
        return {"success": True, "results": [{"title": "T", "url": "u", "snippet": "s"}]}
    monkeypatch.setattr(web, "_ddgs_search", fake_ddgs)
    out = web.search("北京天气", limit=3)
    assert out["success"] is True
    assert called["ddgs"] == ("北京天气", 3)
    assert out["results"][0]["title"] == "T"


def test_search_uses_tavily_when_key_set(monkeypatch):
    monkeypatch.setenv("TAVILY_API_KEY", "tvly-x")
    called = {}
    def fake_tavily(query, limit):
        called["tavily"] = True
        return {"success": True, "results": []}
    monkeypatch.setattr(web, "_tavily_search", fake_tavily)
    web.search("q")
    assert called.get("tavily") is True


def test_ddgs_normalizes_hits(monkeypatch):
    class FakeDDGS:
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def text(self, query, max_results): return [{"title": "A", "href": "http://a", "body": "ba"}]
    monkeypatch.setattr(web, "_DDGS", FakeDDGS)
    out = web._ddgs_search("q", 5)
    assert out["success"] is True
    assert out["results"][0] == {"title": "A", "url": "http://a", "snippet": "ba"}


def test_extract_uses_trafilatura(monkeypatch):
    monkeypatch.setattr(web, "_http_get", lambda url: "<html><body><p>hello world</p></body></html>")
    monkeypatch.setattr(web, "_trafilatura_extract", lambda html: "hello world")
    out = web.extract("http://x")
    assert out["success"] is True
    assert "hello world" in out["text"]


def test_extract_failure_returns_error(monkeypatch):
    def boom(url): raise RuntimeError("net down")
    monkeypatch.setattr(web, "_http_get", boom)
    out = web.extract("http://x")
    assert out["success"] is False
    assert "net down" in out["error"]
