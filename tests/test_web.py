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
        def __init__(self, **kw): pass                       # 真 DDGS 构造器收 timeout 等
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def text(self, query, **kw): return [{"title": "A", "href": "http://a", "body": "ba"}]
    monkeypatch.setattr(web, "_DDGS", FakeDDGS)
    out = web._ddgs_search("q", 5)
    assert out["success"] is True
    assert out["results"][0] == {"title": "A", "url": "http://a", "snippet": "ba"}


def test_ddgs_uses_multi_engine_auto_and_timeout(monkeypatch):
    """免 key 兜底的核心:ddgs 用 backend='auto' 并发多引擎(DuckDuckGo 被限流时
    Bing/Brave/Google/Wikipedia 自动补位、聚合结果),且给库构造器传 timeout(库内硬超时)。
    这就是【用户没配 Tavily 时不花一分钱】的容错来源 —— ddgs 9.x 本就是多引擎元搜索。"""
    seen: dict = {}

    class FakeDDGS:
        def __init__(self, **kw): seen["ctor"] = kw
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def text(self, query, **kw):
            seen["text"] = kw
            return [{"title": "A", "href": "http://a", "body": "b"}]

    monkeypatch.setattr(web, "_DDGS", FakeDDGS)
    out = web._ddgs_search("q", 3)
    assert out["success"] is True
    assert seen["text"].get("backend") == "auto", "必须显式多引擎 auto(免 key 兜底)"
    assert "timeout" in seen["ctor"], "必须给 ddgs 库传 timeout(库内每引擎硬超时)"


def test_ddgs_search_times_out_instead_of_hanging(monkeypatch):
    """ddgs 9.x 库本身无超时参数 → 网络卡死会无限挂起,拖到 smolagents 执行器超时才以丑陋
    traceback 收场(2026-06-16 真机:查天气 117s 后 TimeoutError)。_ddgs_search 必须用硬截止
    时间兜底:超时即返回诚实错误,而不是挂死。"""
    import threading
    entered = threading.Event()

    class HangingDDGS:
        def __init__(self, **kw): pass
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def text(self, query, **kw):
            entered.set()
            threading.Event().wait(5.0)   # 模拟卡死的网络请求(永远等不到的事件超时返回)
            return []

    monkeypatch.setattr(web, "_DDGS", HangingDDGS)
    monkeypatch.setattr(web, "_DDGS_TIMEOUT_S", 0.2)
    out = web._ddgs_search("成都明天天气", 5)
    assert entered.wait(1.0), "应真的进了搜索线程"
    assert out["success"] is False
    assert "超时" in out["error"], out


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
