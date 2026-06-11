"""EgressPolicy —— host 侧网络 allowlist(契约 §5 + spec §6.4)。

沙箱默认断网(Seatbelt deny network*);网络只能经 broker 走本 allowlist:
仅 LLM 端点 + web-search provider + 已配 MCP + 用户批准域名。精确 host 匹配(防子域伪冒)。
"""
from __future__ import annotations

from urllib.parse import urlparse


def _host_of(url_or_host: str) -> str:
    """从 url 或裸 host 抽 host(小写,去端口)。"""
    s = url_or_host.strip()
    if "://" in s:
        netloc = urlparse(s).netloc
    else:
        netloc = s.split("/", 1)[0]
    host = netloc.split("@")[-1].split(":")[0].lower()
    return host


class EgressPolicy:
    def __init__(self, *, llm_hosts: set[str], search_hosts: set[str],
                 mcp_hosts: set[str]) -> None:
        self._base = {h.lower() for h in (llm_hosts | search_hosts | mcp_hosts)}
        self._user: set[str] = set()

    def allowed(self, url_or_host: str) -> bool:
        """精确 host 在白名单(base 或用户批准)→ True;否则 False。"""
        host = _host_of(url_or_host)
        if not host:
            return False
        return host in self._base or host in self._user

    def allow(self, host: str) -> None:
        """用户批准后加白(broker 在 approve 网络动作时调用)。"""
        self._user.add(_host_of(host))

    def add_hosts(self, hosts: "set[str] | frozenset[str] | tuple[str, ...]") -> None:
        """热更新:批量加白出网 host(registry 注册网络类能力时调用,补声明 egress_hosts)。

        fail-closed 方向不变:未声明的 host 仍被 allowed() 拒。
        重复加白幂等(set.add)。
        """
        for h in hosts:
            normalized = _host_of(h)
            if normalized:
                self._base.add(normalized)
