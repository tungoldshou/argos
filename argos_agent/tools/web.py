"""broker-gated web 工具的 host 侧真实现(契约 §4).

委托旧 argos_agent.web(provider 抽象:DDGS 免费兜底 / Tavily 升级 / trafilatura 取页)。
网络出口已由 broker 的 EgressPolicy 在调用前裁决;本模块只做格式化。
"""
from __future__ import annotations

from argos_agent import web

_EXTRACT_COMPRESS_THRESHOLD = 6000


def web_search(query: str, limit: int = 5) -> str:
    """联网搜索,返回若干结果(标题+链接+摘要)。"""
    res = web.search(query, limit)
    if not res.get("success"):
        return f"搜索失败:{res.get('error', '未知错误')}"
    results = res.get("results") or []
    if not results:
        return "没有搜到结果。"
    lines = []
    for i, r in enumerate(results, 1):
        lines.append(f"{i}. {r.get('title', '')}\n   {r.get('url', '')}\n   {r.get('snippet', '')}")
    return "\n".join(lines)


def web_extract(url: str) -> str:
    """取一个网页的正文(已去导航/广告噪声)。长正文截断(压缩留 Phase 4 接 model)。"""
    res = web.extract(url)
    if not res.get("success"):
        return f"取页失败:{res.get('error', '未知错误')}"
    text = res.get("text") or ""
    if len(text) <= _EXTRACT_COMPRESS_THRESHOLD:
        return text or "(页面无可提取正文)"
    return text[:8000] + f"\n…(正文共 {len(text)} 字符,已截断)"


def host_for(action: str, args: dict) -> str:
    """从 web 动作的 args 抽要校验 egress 的 host(broker 用)。"""
    if action == "web_extract":
        return args.get("url", "")
    return ""   # web_search 的出口由 provider host 决定,broker 用 search_hosts 白名单覆盖
