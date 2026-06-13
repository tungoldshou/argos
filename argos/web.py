"""联网工具的 provider 抽象 —— 搜索 + 取页。

设计原则(呼应 Argos 安全哲学):
  · 只读外部:只搜索、取页读取,没有任何写外部/上传能力。
  · 错误作为数据返回(不抛异常),让 agent 看到失败自纠(ReAct)。
  · 多 provider:免费 DDGS 兜底(无需 key,下载即用),有 TAVILY_API_KEY 升级 Tavily。
"""
from __future__ import annotations

import os

# 延迟/可 monkeypatch 的间接层:测试替换这些符号即可,不碰真网。
try:
    from ddgs import DDGS as _DDGS
except Exception:  # pragma: no cover - 包缺失时降级,运行期给出诚实错误
    _DDGS = None


def _ddgs_search(query: str, limit: int) -> dict:
    """免费 DuckDuckGo 搜索(无需 key)。归一化为 {title,url,snippet}。"""
    if _DDGS is None:
        return {"success": False, "error": "ddgs 包不可用,无法免费搜索;可配置 TAVILY_API_KEY 升级。"}
    try:
        results = []
        with _DDGS() as client:
            for i, hit in enumerate(client.text(query, max_results=max(1, int(limit)))):
                if i >= max(1, int(limit)):
                    break
                results.append({
                    "title": str(hit.get("title", "")),
                    "url": str(hit.get("href") or hit.get("url") or ""),
                    "snippet": str(hit.get("body", "")),
                })
        return {"success": True, "results": results}
    except Exception as e:  # noqa: BLE001
        return {"success": False, "error": f"DuckDuckGo 搜索失败:{e}"}


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
        return {"success": False, "error": f"Tavily 搜索失败:{e}"}


# 各 provider 的出口 host(broker 的 EgressPolicy 据此 fail-closed 校验 web_search 出网)。
TAVILY_HOST = "api.tavily.com"
DDGS_HOST = "duckduckgo.com"


def search(query: str, limit: int = 5) -> dict:
    """联网搜索。有 TAVILY_API_KEY → Tavily;否则 → 免费 DDGS。"""
    if os.environ.get("TAVILY_API_KEY", "").strip():
        return _tavily_search(query, limit)
    return _ddgs_search(query, limit)


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


def _http_get(url: str) -> str:
    """抓一个 URL 的原始 HTML(只读、超时)。#6 SSRF:逐跳跟随 redirect(最多 5),每跳校验 host
    非私网/保留(防白名单 host redirect 到内网/云元数据绕过 egress);命中即拒,不发该请求。"""
    import httpx
    from urllib.parse import urljoin, urlparse
    cur = url
    with httpx.Client(timeout=30, follow_redirects=False,
                      headers={"User-Agent": "Argos/0.1"}) as client:
        for _ in range(6):   # 初始 + 最多 5 跳 redirect
            host = urlparse(cur).hostname or ""
            if _is_blocked_host(host):
                raise ValueError(f"SSRF 防护:拒绝访问私网/保留地址 {host!r}")
            r = client.get(cur)
            if r.is_redirect:
                loc = str(r.headers.get("location") or "")
                if not loc:
                    break
                cur = urljoin(str(r.url), loc)   # 相对 redirect 补全
                continue
            r.raise_for_status()
            return r.text
        raise ValueError("取页失败:redirect 跳数超限(>5)")


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
    """取网页正文:抓 HTML → trafilatura 抽正文 → 抽不出则去标签兜底。"""
    try:
        html = _http_get(url)
    except Exception as e:  # noqa: BLE001
        return {"success": False, "error": f"取页失败:{e}"}
    try:
        text = _trafilatura_extract(html)
    except Exception:
        text = None
    if not text:
        text = _strip_tags(html)
    return {"success": True, "text": text}
