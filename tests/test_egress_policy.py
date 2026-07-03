from __future__ import annotations

import pytest

from argos.sandbox.egress import EgressPolicy


def test_llm_and_search_hosts_allowed():
    pol = EgressPolicy(
        llm_hosts={"api.minimaxi.com"},
        search_hosts={"api.tavily.com", "duckduckgo.com"},
        mcp_hosts=set(),
    )
    assert pol.allowed("https://api.minimaxi.com/anthropic") is True
    assert pol.allowed("api.tavily.com") is True
    assert pol.allowed("https://duckduckgo.com/?q=x") is True


def test_unknown_host_denied():
    pol = EgressPolicy(llm_hosts={"api.minimaxi.com"}, search_hosts=set(), mcp_hosts=set())
    assert pol.allowed("https://evil.example.com/exfil") is False
    assert pol.allowed("169.254.169.254") is False


def test_user_approved_host_added():
    pol = EgressPolicy(llm_hosts=set(), search_hosts=set(), mcp_hosts=set())
    assert pol.allowed("docs.python.org") is False
    pol.allow("docs.python.org")
    assert pol.allowed("https://docs.python.org/3/") is True


def test_subdomain_not_implicitly_allowed():
    pol = EgressPolicy(llm_hosts={"api.minimaxi.com"}, search_hosts=set(), mcp_hosts=set())
    assert pol.allowed("https://api.minimaxi.com.evil.com/") is False
