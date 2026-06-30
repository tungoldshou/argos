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


# ── #8 CC对齐:trafilatura 抽空 → 模型兜底(对齐 CC WebFetch),再退正则 ──────────────────
def test_extract_model_fallback_when_trafilatura_empty(monkeypatch):
    """trafilatura 抽空(JS 渲染页)→ 用模型兜底的结果。"""
    monkeypatch.setattr(web, "_http_get", lambda url: "<html><body>JS app</body></html>")
    monkeypatch.setattr(web, "_trafilatura_extract", lambda html: None)
    monkeypatch.setattr(web, "_model_extract", lambda html: "# Clean Markdown\nbody")
    out = web.extract("http://x")
    assert out["success"] is True and out["text"] == "# Clean Markdown\nbody"


def test_extract_regex_fallback_when_model_unavailable(monkeypatch):
    """trafilatura 抽空 + 模型不可用(无 key)→ 回落正则去标签,绝不阻断。"""
    monkeypatch.setattr(web, "_http_get", lambda url: "<html><body><p>plain text</p></body></html>")
    monkeypatch.setattr(web, "_trafilatura_extract", lambda html: None)
    monkeypatch.setattr(web, "_model_extract", lambda html: None)   # 模型不可用
    out = web.extract("http://x")
    assert out["success"] is True and "plain text" in out["text"]


def test_model_extract_returns_none_without_key(monkeypatch):
    """无 active key → _model_extract 直接返 None(不发任何模型调用)。"""
    import argos.config as C
    monkeypatch.setattr(C, "active_key", lambda: None)
    assert web._model_extract("<html>...</html>") is None


# ── 搜索质量护栏(2026-06-22 真机审计:中文天气 query 被拉出色情/约炮 SEO 垃圾)──────────

def test_ddgs_passes_safesearch_on_and_inferred_region(monkeypatch):
    """A1+A2:免 key DDGS 必须传 safesearch="on"(严格档),并按 query 语言推断 region
    (中文 → cn-zh,避免 us-en 默认把中文 query 拉出英文垃圾)。"""
    seen: dict = {}

    class FakeDDGS:
        def __init__(self, **kw): pass
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def text(self, query, **kw):
            seen.update(kw)
            return [{"title": "成都天气", "href": "http://weather.cn/cd", "body": "晴 26°C"}]

    monkeypatch.setattr(web, "_DDGS", FakeDDGS)
    out = web._ddgs_search("成都今天天气", 5)
    assert out["success"] is True
    assert seen.get("safesearch") == "on", "必须严格档 safesearch"
    assert seen.get("region") == "cn-zh", "中文 query 应推断 cn-zh 区"


def test_infer_region_by_script():
    assert web._infer_region("成都今天天气") == "cn-zh"
    assert web._infer_region("Chengdu weather today") == "wt-wt"
    assert web._infer_region("東京の天気はどう") == "jp-jp"      # 含假名 → 日区
    assert web._infer_region("서울 날씨") == "kr-kr"            # 谚文 → 韩区


def test_filter_results_drops_spam_keeps_lookalike_legit():
    """A5:过滤掉高把握成人/垃圾结果,但绝不误伤含 'sex' 子串的正常域名(essex/sussex)。"""
    raw = [
        {"title": "Casual Dating Tryhuk", "url": "https://linkedin.com/jobs/frau+sex+casual+dating", "snippet": "porn"},
        {"title": "University of Essex", "url": "https://www.essex.ac.uk/weather", "snippet": "campus"},
        {"title": "Chengdu Weather", "url": "https://accuweather.com/cd", "snippet": "26C"},
    ]
    out = web._filter_results(raw, 5)
    urls = [r["url"] for r in out]
    assert "https://www.essex.ac.uk/weather" in urls, "essex 含 sex 子串但是正常结果,不能误杀"
    assert "https://accuweather.com/cd" in urls
    assert all("casual" not in u for u in urls), "约炮/色情 SEO 垃圾必须被过滤"


def test_filter_results_drops_empty_and_dedups_and_caps():
    raw = [
        {"title": "", "url": "", "snippet": ""},                       # 空 url → 丢
        {"title": "", "url": "http://a.com/x", "snippet": ""},         # title+snippet 全空 → 丢
        {"title": "A", "url": "http://a.com/p", "snippet": "s1"},
        {"title": "A dup", "url": "http://a.com/p/", "snippet": "s2"},  # 同 host+path(尾斜杠归一)→ 去重
        {"title": "B", "url": "http://b.com", "snippet": "s3"},
        {"title": "C", "url": "http://c.com", "snippet": "s4"},
    ]
    out = web._filter_results(raw, 2)
    assert len(out) == 2, "应截到 limit"
    assert out[0]["url"] == "http://a.com/p"
    assert out[1]["url"] == "http://b.com"


def test_search_applies_filter_for_both_providers(monkeypatch):
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)
    monkeypatch.setattr(web, "_ddgs_search", lambda q, l: {
        "success": True,
        "results": [
            {"title": "spam", "url": "http://x.com/porn", "snippet": "x"},
            {"title": "ok", "url": "http://ok.com", "snippet": "good"},
        ],
    })
    out = web.search("q", 5)
    assert out["success"] is True
    assert [r["url"] for r in out["results"]] == ["http://ok.com"]


# ── A3:web_search 格式化层 snippet 截断(防垃圾长摘要撑爆输入 token)──────────────────

def test_tools_web_search_caps_snippet(monkeypatch):
    from argos.tools import web as toolsweb
    long_body = "x " * 1000   # ~2000 字符
    monkeypatch.setattr(toolsweb.web, "search", lambda q, l=5: {
        "success": True,
        "results": [{"title": "T", "url": "http://t.com", "snippet": long_body}],
    })
    out = toolsweb.web_search("q")
    assert "…" in out, "超长摘要应截断并加省略号"
    # 截断后单条结果远小于原始 2000 字符正文
    assert len(out) < 500, f"摘要未被有效截断,len={len(out)}"


def test_tools_web_search_collapses_newlines(monkeypatch):
    from argos.tools import web as toolsweb
    monkeypatch.setattr(toolsweb.web, "search", lambda q, l=5: {
        "success": True,
        "results": [{"title": "T", "url": "http://t.com", "snippet": "line1\n\n  line2\tline3"}],
    })
    out = toolsweb.web_search("q")
    assert "line1 line2 line3" in out, "摘要内的换行/多空白应折叠为单空格"


# ── web_extract 健壮性(2026-06-22:BBC weather UNEXPECTED_EOF 一次抖动就永久失败)──────

def test_transient_error_classification():
    import ssl, httpx
    assert web._transient_error(httpx.ConnectError("x")) is True
    assert web._transient_error(ssl.SSLError("UNEXPECTED_EOF")) is True
    assert web._transient_error(ValueError("ssrf")) is False        # SSRF/跳数超限是终态
    req = httpx.Request("GET", "http://x")
    resp = httpx.Response(404, request=req)
    assert web._transient_error(httpx.HTTPStatusError("404", request=req, response=resp)) is False


def test_http_get_retries_transient_then_succeeds(monkeypatch):
    import httpx
    monkeypatch.setattr(web, "_HTTP_BACKOFF_S", 0)        # 不真睡
    calls = {"n": 0, "uas": []}
    def fake_once(url, *, user_agent):
        calls["n"] += 1
        calls["uas"].append(user_agent)
        if calls["n"] == 1:
            raise httpx.ConnectError("transient blip")
        return "<html>ok</html>"
    monkeypatch.setattr(web, "_http_get_once", fake_once)
    out = web._http_get("http://x")
    assert out == "<html>ok</html>"
    assert calls["n"] == 2, "瞬时错误应重试一次后成功"


def test_http_get_last_retry_uses_browser_ua(monkeypatch):
    import httpx
    monkeypatch.setattr(web, "_HTTP_BACKOFF_S", 0)
    monkeypatch.setattr(web, "_HTTP_RETRIES", 2)
    seen = []
    def always_fail(url, *, user_agent):
        seen.append(user_agent)
        raise httpx.ConnectError("nope")
    monkeypatch.setattr(web, "_http_get_once", always_fail)
    with pytest.raises(httpx.ConnectError):
        web._http_get("http://x")
    assert len(seen) == 3, "总尝试 = 1 + 2 重试"
    assert seen[-1] == web._BROWSER_UA, "末次重试换浏览器 UA 兜底挑剔 CDN"
    assert seen[0] == "Argos/0.1", "首次仍以诚实 bot 身份请求"


def test_http_get_does_not_retry_ssrf(monkeypatch):
    """SSRF(ValueError)是终态:必须立即抛出,绝不重试。"""
    calls = {"n": 0}
    def ssrf(url, *, user_agent):
        calls["n"] += 1
        raise ValueError("blocked")
    monkeypatch.setattr(web, "_http_get_once", ssrf)
    with pytest.raises(ValueError):
        web._http_get("http://x")
    assert calls["n"] == 1, "SSRF/终态错误不重试"


def test_extract_transient_error_gives_actionable_message(monkeypatch):
    import ssl
    monkeypatch.setattr(web, "_http_get", lambda url: (_ for _ in ()).throw(ssl.SSLError("UNEXPECTED_EOF")))
    out = web.extract("https://www.bbc.com/weather/1815286")
    assert out["success"] is False
    assert "bbc.com" in out["error"], "应点明 host"
    assert "UNEXPECTED_EOF" in out["error"]
    # 可操作:暗示重试/换源
    assert ("retry" in out["error"].lower() or "重试" in out["error"])


def test_tools_web_extract_no_double_prefix(monkeypatch):
    """B4:内层去前缀后,'取页失败:'/‘Fetch failed:’ 只出现一次。"""
    from argos.tools import web as toolsweb
    monkeypatch.setattr(toolsweb.web, "extract", lambda url: {"success": False, "error": "net down"})
    out = toolsweb.web_extract("http://x")
    assert out.count("取页失败") == 1, f"前缀应只出现一次,得到:{out!r}"
    assert "Fetch failed: Fetch failed" not in out
