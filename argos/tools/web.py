"""broker-gated web 工具的 host 侧真实现(契约 §4).

委托旧 argos.web(provider 抽象:DDGS 免费兜底 / Tavily 升级 / trafilatura 取页)。
网络出口已由 broker 的 EgressPolicy 在调用前裁决;本模块只做格式化。
"""
from __future__ import annotations

from argos import web
from argos.i18n import t

_EXTRACT_COMPRESS_THRESHOLD = 6000


def web_search(query: str, limit: int = 5) -> str:
    """联网搜索,返回若干结果(标题+链接+摘要)。"""
    res = web.search(query, limit)
    if not res.get("success"):
        return t("tools.web.search_failed", error=res.get("error") or t("tools.web.unknown_error"))
    results = res.get("results") or []
    if not results:
        return t("tools.web.search_no_results")
    lines = []
    for i, r in enumerate(results, 1):
        lines.append(f"{i}. {r.get('title', '')}\n   {r.get('url', '')}\n   {r.get('snippet', '')}")
    return "\n".join(lines)


def web_extract(url: str) -> str:
    """取一个网页的正文(已去导航/广告噪声)。长正文截断(压缩留 Phase 4 接 model)。"""
    res = web.extract(url)
    if not res.get("success"):
        return t("tools.web.extract_failed", error=res.get("error") or t("tools.web.unknown_error"))
    text = res.get("text") or ""
    if len(text) <= _EXTRACT_COMPRESS_THRESHOLD:
        return text or t("tools.web.extract_empty")
    return text[:8000] + t("tools.web.extract_truncated", total=len(text))


def host_for(action: str, args: dict) -> str:
    """从 web 动作抽要校验 egress 的 host(broker 用)。
    web_extract → 目标 url 的 host;web_search → 当前生效 provider 的出口 host。"""
    if action == "web_extract":
        return args.get("url", "")
    if action == "web_search":
        return web.active_search_host()   # I3:解析活跃 provider host,broker fail-closed 校验
    return ""


def extract_url_blocked(url: str) -> bool:
    """web_extract 的出网判据:目标 URL 的 host 是否被 SSRF 防护拒(私网/回环/保留/云元数据)。
    web_extract 的目标由 agent 动态选(能力清单声明 egress_hosts=("*"))→ 放行任意【公网】host,
    只硬挡内网/元数据(此处是 broker 边界第一层;_http_get 内逐跳再校验是第二层)。
    无法解析出 host → fail-closed 视为被拒。"""
    from urllib.parse import urlparse
    u = url if "://" in (url or "") else f"http://{url}"
    host = (urlparse(u).hostname or "").strip()
    if not host:
        return True   # 解析不出 host → 拒(fail-closed)
    return web._is_blocked_host(host)
