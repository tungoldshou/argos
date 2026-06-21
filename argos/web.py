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
#   · _DDGS_TIMEOUT_S → 外层 daemon 线程的硬截止,最终兜底防库内极端挂死。必须 < sandbox 子进程
#     smolagents 执行器的 30s 上限(2026-06-16 真机:旧版无护栏,卡死 117s 后甩 TimeoutError)。
_DDGS_TIMEOUT_S = 20.0
_DDGS_ENGINE_TIMEOUT_S = 8


def _ddgs_search(query: str, limit: int) -> dict:
    """免 key 多引擎元搜索(backend=auto:DuckDuckGo/Bing/Brave/Google/… 聚合)。
    归一化为 {title,url,snippet};库内软超时 + 外层 daemon 线程硬超时双护栏(防卡死)。"""
    if _DDGS is None:
        return {"success": False, "error": t("web.ddgs_unavailable")}

    def _blocking() -> list[dict]:
        results: list[dict] = []
        # backend="auto":并发多引擎 + 聚合,单引擎被限流时其它引擎补位(免 key 兜底的关键)。
        with _DDGS(timeout=_DDGS_ENGINE_TIMEOUT_S) as client:
            for i, hit in enumerate(
                client.text(query, max_results=max(1, int(limit)), backend="auto")
            ):
                if i >= max(1, int(limit)):
                    break
                results.append({
                    "title": str(hit.get("title", "")),
                    "url": str(hit.get("href") or hit.get("url") or ""),
                    "snippet": str(hit.get("body", "")),
                })
        return results

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
        return {"success": False, "error": t("web.fetch_failed", exc=e)}
    try:
        text = _trafilatura_extract(html)
    except Exception:
        text = None
    if not text:
        text = _strip_tags(html)
    return {"success": True, "text": text}
