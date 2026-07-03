"""Internal documentation."""
from __future__ import annotations

from urllib.parse import urlparse


def _host_of(url_or_host: str) -> str:
    """Internal documentation."""
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
        """Internal documentation."""
        host = _host_of(url_or_host)
        if not host:
            return False
        return host in self._base or host in self._user

    def allow(self, host: str) -> None:
        """Internal documentation."""
        self._user.add(_host_of(host))

    def add_hosts(self, hosts: "set[str] | frozenset[str] | tuple[str, ...]") -> None:
        """Internal documentation."""
        for h in hosts:
            normalized = _host_of(h)
            if normalized:
                self._base.add(normalized)
