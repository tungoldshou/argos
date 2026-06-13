"""#6 SSRF 防护:web_extract 的 _http_get 拒私网/保留/loopback/link-local 地址 + 云元数据端点,
并逐跳校验 redirect(防白名单 host redirect 到内网绕过 egress)。egress 白名单是域名层第一防线,
此处是 IP 层第二防线(直接 IP url / redirect 到 IP / 云元数据)。"""
from __future__ import annotations

from argos.web import _is_blocked_host, extract


def test_blocks_cloud_metadata_endpoint():
    assert _is_blocked_host("169.254.169.254") is True   # AWS/GCP/Azure 元数据端点(link-local)


def test_blocks_loopback_private_linklocal():
    for h in ("127.0.0.1", "10.0.0.5", "192.168.1.1", "172.16.0.1", "::1",
              "localhost", "0.0.0.0", "metadata.google.internal"):
        assert _is_blocked_host(h) is True, h


def test_allows_public_host():
    assert _is_blocked_host("example.com") is False
    assert _is_blocked_host("93.184.216.34") is False    # 公网 IP


def test_extract_rejects_private_url_before_request():
    # 私网/元数据 url → 在发请求【前】被拒(success=False),不触发任何网络副作用。
    out = extract("http://169.254.169.254/latest/meta-data/")
    assert out["success"] is False
    assert "SSRF" in out["error"] or "私网" in out["error"] or "169.254" in out["error"]


def test_extract_rejects_loopback_url():
    out = extract("http://127.0.0.1:8080/admin")
    assert out["success"] is False
