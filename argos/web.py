"""联网工具的 provider 抽象 —— 搜索 + 取页。

设计原则(呼应 Argos 安全哲学):
  · 只读外部:只搜索、取页读取,没有任何写外部/上传能力。
  · 错误作为数据返回(不抛异常),让 agent 看到失败自纠(ReAct)。
  · 多 provider:免费 DDGS 兜底(无需 key,下载即用),有 TAVILY_API_KEY 升级 Tavily。
"""
from __future__ import annotations

import os
import threading

from argos.i18n import t

# 延迟/可 monkeypatch 的间接层:测试替换这些符号即可,不碰真网。
try:
    from ddgs import DDGS as _DDGS
except Exception:  # pragma: no cover - 包缺失时降级,运行期给出诚实错误
    _DDGS = None

# ── 免费、免 key 的多引擎兜底(用户没配 Tavily / 单引擎被限流时的容错核心)──────────────
# ddgs 9.x 不是"只有 DuckDuckGo":它是【多引擎元搜索】。backend="auto" 会并发查
# DuckDuckGo / Bing / Brave / Google / Mojeek / Yandex / Startpage / Wikipedia 等十余个引擎
# 并【聚合】结果 —— 单个引擎挂了(实测 DuckDuckGo 常被限流返回 "No results")不影响整体,
# 其它引擎自动补位。这就是【没有 Tavily key 也不花一分钱】的联网搜索:不替任何用户付费。
# 两道超时护栏:
#   · _DDGS_ENGINE_TIMEOUT_S → 传给 ddgs 库构造器,库内每个引擎/批次的软超时(够慢引擎返回,
#     实测 Bing ~3s、Brave ~1.5s,8s 留足余量又不拖沓);
#   · _DDGS_TIMEOUT_S → 外层 daemon 线程的硬截止,最终兜底防库内极端挂死(2026-06-16 真机:旧版
#     无护栏,卡死 117s 后甩 TimeoutError)。web_search/web_extract 现走 host 侧 broker bridge
#     (300s 预算,broker.py 的 _bridge_timeout),不在 30s 的 Seatbelt smolagents 子进程内 —— 20s
#     是为体感留的余量,而非旧 sandbox 上限的约束。
_DDGS_TIMEOUT_S = 20.0
_DDGS_ENGINE_TIMEOUT_S = 8
_HTTP_RETRIES = 2            # web_extract 抓页的额外重试次数(总尝试 = 1 + _HTTP_RETRIES)
_HTTP_BACKOFF_S = 0.5        # 重试前退避基数(指数:0.5s, 1s);测试 monkeypatch 为 0 不真睡
# 浏览器 UA 兜底:不少 CDN 对未知 bot UA 直接 RST/截断 TLS(2026-06-22 真机:BBC weather 报
# UNEXPECTED_EOF)。末次重试换常见浏览器 UA,常把瞬时 TLS 截断变成干净 200。
_BROWSER_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)

# 高精度成人/垃圾标记:只挑几乎不会出现在正常结果里的 token(避免误伤 essex/sussex 等
# 含 "sex" 子串的正常域名 → "sex" 只在带分隔符时才算)。这不是完整黑名单,只是廉价第一道,
# 与 safesearch="on" 叠加兜底(backend="auto" 里 yandex/bing 等引擎会忽略 safesearch)。
_SPAM_TOKENS = (
    "porn", "erotik", "ladyboy", "xxx", "escort+", "+escort",
    "casual dating", "casual+dating", "+sex", "sex+", "/sex/", " sex ",
)


def _infer_region(query: str) -> str:
    """按 query 文字推断 ddgs region。免 key DDGS 默认 us-en 会把中文 query 按美英区排序
    → 相关性差、易混入英文垃圾(2026-06-22 真机:中文"成都天气"被 us-en 拉出约炮/色情垃圾)。
    先判假名/谚文(日韩),再判中日韩统一表意(无假名/谚文则判中文),否则世界区。"""
    q = query or ""
    if any(0x3040 <= ord(c) <= 0x30FF for c in q):       # 日文假名
        return "jp-jp"
    if any(0xAC00 <= ord(c) <= 0xD7A3 for c in q):       # 韩文谚文
        return "kr-kr"
    if any(0x4E00 <= ord(c) <= 0x9FFF for c in q):       # 中日韩统一表意 → 判中文
        return "cn-zh"
    return "wt-wt"


def _filter_results(results: list[dict], limit: int) -> list[dict]:
    """host 侧结果清洗(库层 safesearch 不可靠时的兜底,返回新 list 不改原对象):
    丢空 url、丢 title+snippet 全空、丢命中高精度成人/垃圾 token 的项;按归一化 host+path 去重;
    最后截到 limit。保守过滤——只挡极高把握的垃圾,绝不误伤正常结果。"""
    from urllib.parse import urlparse
    seen: set[str] = set()
    out: list[dict] = []
    for r in results:
        url = str(r.get("url") or "").strip()
        title = str(r.get("title") or "").strip()
        snippet = str(r.get("snippet") or "").strip()
        if not url or (not title and not snippet):
            continue
        hay = f" {url} {title} ".lower()
        if any(tok in hay for tok in _SPAM_TOKENS):
            continue
        p = urlparse(url if "://" in url else f"http://{url}")
        key = f"{(p.hostname or '').lower()}{(p.path or '').rstrip('/')}"
        if key in seen:
            continue
        seen.add(key)
        out.append(r)
        if len(out) >= max(1, int(limit)):
            break
    return out


def _ddgs_search(query: str, limit: int) -> dict:
    """免 key 多引擎元搜索(backend=auto:DuckDuckGo/Bing/Brave/Google/… 聚合)。
    归一化为 {title,url,snippet};库内软超时 + 外层 daemon 线程硬超时双护栏(防卡死)。
    质量护栏:safesearch="on"(严格档)+ region(按 query 语言推断)收紧来源。"""
    if _DDGS is None:
        return {"success": False, "error": t("web.ddgs_unavailable")}

    lim = max(1, int(limit))
    region = _infer_region(query)

    def _blocking() -> list[dict]:
        results: list[dict] = []
        # backend="auto":并发多引擎 + 聚合,单引擎被限流时其它引擎补位(免 key 兜底的关键)。
        # safesearch="on":严格过滤成人内容(部分引擎忽略,故 search() 再叠加 _filter_results)。
        with _DDGS(timeout=_DDGS_ENGINE_TIMEOUT_S) as client:
            for hit in client.text(
                query, max_results=lim, backend="auto",
                safesearch="on", region=region,
            ):
                results.append({
                    "title": str(hit.get("title", "")),
                    "url": str(hit.get("href") or hit.get("url") or ""),
                    "snippet": str(hit.get("body", "")),
                })
        return results[:lim]

    box: dict[str, object] = {}

    def _target() -> None:
        try:
            box["results"] = _blocking()
        except Exception as e:  # noqa: BLE001 — 错误作为数据回传主线程(ReAct:让 agent 看到失败)
            box["error"] = e

    _thr = threading.Thread(target=_target, daemon=True)
    _thr.start()
    _thr.join(_DDGS_TIMEOUT_S)
    if _thr.is_alive():
        return {"success": False,
                "error": t("web.search_timeout", timeout=int(_DDGS_TIMEOUT_S))}
    if "error" in box:
        return {"success": False,
                "error": t("web.search_all_failed", error=box["error"])}
    return {"success": True, "results": box.get("results", [])}


def _tavily_search(query: str, limit: int) -> dict:
    """Tavily 搜索(需 TAVILY_API_KEY,质量更好)。归一化为 {title,url,snippet}。"""
    import httpx
    key = os.environ.get("TAVILY_API_KEY", "")
    try:
        r = httpx.post(
            "https://api.tavily.com/search",
            json={"api_key": key, "query": query, "max_results": min(int(limit), 20)},
            timeout=60,
        )
        r.raise_for_status()
        data = r.json()
        results = [{
            "title": str(it.get("title", "")),
            "url": str(it.get("url", "")),
            "snippet": str(it.get("content", "")),
        } for it in (data.get("results") or [])]
        return {"success": True, "results": results}
    except Exception as e:  # noqa: BLE001
        return {"success": False, "error": t("web.tavily_failed", exc=e)}


# 各 provider 的出口 host(broker 的 EgressPolicy 据此 fail-closed 校验 web_search 出网)。
TAVILY_HOST = "api.tavily.com"
DDGS_HOST = "duckduckgo.com"


def search(query: str, limit: int = 5) -> dict:
    """联网搜索。有 TAVILY_API_KEY → Tavily;否则 → 免费 DDGS。
    无论哪个 provider,成功结果都过一道 _filter_results(去空/去垃圾/去重),再返回。"""
    if os.environ.get("TAVILY_API_KEY", "").strip():
        res = _tavily_search(query, limit)
    else:
        res = _ddgs_search(query, limit)
    if res.get("success"):
        res = {**res, "results": _filter_results(res.get("results") or [], max(1, int(limit)))}
    return res


def active_search_host() -> str:
    """当前生效 search provider 的出口 host —— broker 用它 fail-closed 校验 egress。
    有 TAVILY_API_KEY → Tavily(api.tavily.com);否则 → 免费 DDGS(duckduckgo.com)。"""
    if os.environ.get("TAVILY_API_KEY", "").strip():
        return TAVILY_HOST
    return DDGS_HOST


def _is_blocked_host(host: str) -> bool:
    """#6 SSRF 防护:私网/保留/loopback/link-local/unspecified IP + localhost/云元数据名 → 拒。
    egress 白名单是域名层第一防线;此处是 IP 层第二防线(直接 IP url / redirect 到 IP / 元数据端点)。
    域名(非 IP 字面量)交 egress 白名单管;此处只拦 IP 字面量与已知内网名(不做 DNS 解析,避免
    引入 DNS 依赖/时延;DNS rebinding 由 egress 白名单限制可达域名缓解)。"""
    import ipaddress
    h = (host or "").strip().lower().strip("[]")   # 去 IPv6 字面量括号
    if h in ("localhost", "0.0.0.0", "metadata.google.internal", "metadata", ""):
        return True
    try:
        ip = ipaddress.ip_address(h)
    except ValueError:
        return False   # 非 IP 字面量(域名):egress 白名单做主防护
    return (ip.is_private or ip.is_loopback or ip.is_link_local
            or ip.is_reserved or ip.is_multicast or ip.is_unspecified)


def _transient_error(exc: Exception) -> bool:
    """是否瞬时传输错误(值得重试):httpx.TransportError 子类 + ssl.SSLError。
    4xx/5xx(HTTPStatusError)与 SSRF/跳数超限(ValueError)是终态,绝不重试。"""
    import ssl
    try:
        import httpx
    except Exception:  # pragma: no cover - httpx 必装,纯防御
        return isinstance(exc, ssl.SSLError)
    return isinstance(exc, (httpx.TransportError, ssl.SSLError))


def _http_get_once(url: str, *, user_agent: str) -> str:
    """单次抓取(只读、超时)。#6 SSRF:逐跳跟随 redirect(最多 5),每跳校验 host
    非私网/保留(防白名单 host redirect 到内网/云元数据绕过 egress);命中即拒,不发该请求。"""
    import httpx
    from urllib.parse import urljoin, urlparse
    cur = url
    with httpx.Client(timeout=30, follow_redirects=False,
                      headers={"User-Agent": user_agent}) as client:
        for _ in range(6):   # 初始 + 最多 5 跳 redirect
            host = urlparse(cur).hostname or ""
            if _is_blocked_host(host):
                raise ValueError(t("web.ssrf_blocked", host=host))
            r = client.get(cur)
            if r.is_redirect:
                loc = str(r.headers.get("location") or "")
                if not loc:
                    break
                cur = urljoin(str(r.url), loc)   # 相对 redirect 补全
                continue
            r.raise_for_status()
            return r.text
        raise ValueError(t("web.redirect_limit"))


def _http_get(url: str) -> str:
    """抓 HTML,带瞬时错误重试 + 指数退避;末次重试换浏览器 UA(对付挑剔 CDN 的 TLS 截断)。
    SSRF / 4xx-5xx 是终态立即抛出;只有 httpx 传输错误/SSL 错误才重试(防一次抖动就永久判死)。"""
    import time
    attempts = 1 + max(0, _HTTP_RETRIES)
    last: Exception | None = None
    for i in range(attempts):
        last_try = i == attempts - 1
        # 末次尝试换常见浏览器 UA(默认先以诚实的 Argos/0.1 身份请求,兜底才伪装)。
        ua = _BROWSER_UA if last_try else "Argos/0.1"
        try:
            return _http_get_once(url, user_agent=ua)
        except Exception as e:  # noqa: BLE001 — 分类后决定重试或抛出
            if last_try or not _transient_error(e):
                raise
            last = e
            time.sleep(_HTTP_BACKOFF_S * (2 ** i))
    raise last if last is not None else RuntimeError("unreachable")  # pragma: no cover


def _trafilatura_extract(html: str) -> str | None:
    """用 trafilatura 从 HTML 抽干净正文(markdown)。抽不出返回 None。"""
    import trafilatura
    return trafilatura.extract(html, output_format="markdown")


def _strip_tags(html: str) -> str:
    """兜底去标签:trafilatura 抽不出时用,极简正则去掉 script/style/标签。"""
    import re
    html = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", html, flags=re.S | re.I)
    text = re.sub(r"<[^>]+>", " ", html)
    return re.sub(r"\s+", " ", text).strip()


def extract(url: str) -> dict:
    """取网页正文:抓 HTML → trafilatura 抽正文 → 抽不出则去标签兜底。
    错误分类:瞬时 TLS/连接错误(重试后仍失败)给可操作提示,让 agent 改源而非干瞪眼。"""
    try:
        html = _http_get(url)
    except Exception as e:  # noqa: BLE001
        if _transient_error(e):
            from urllib.parse import urlparse
            host = (urlparse(url if "://" in (url or "") else f"http://{url}").hostname or url)
            return {"success": False, "error": t("web.fetch_transient", host=host, exc=e)}
        return {"success": False, "error": t("web.fetch_failed", exc=e)}
    try:
        text = _trafilatura_extract(html)
    except Exception:
        text = None
    if not text:
        text = _strip_tags(html)
    return {"success": True, "text": text}
