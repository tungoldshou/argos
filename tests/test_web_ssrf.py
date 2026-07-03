"""Internal documentation."""
from __future__ import annotations

from argos.tools.web import extract_url_blocked
from argos.web import _is_blocked_host, extract


def test_extract_url_blocked_allows_public_denies_internal():
    """Internal documentation."""
    for ok in ("https://news.example.com/a?x=1", "http://example.com", "example.com/page",
               "https://93.184.216.34/"):
        assert extract_url_blocked(ok) is False, ok
    for bad in ("http://169.254.169.254/latest/meta-data/", "http://127.0.0.1:8080/admin",
                "http://10.0.0.5/", "http://192.168.1.1/", "http://metadata.google.internal/",
                "http://localhost:9000/", ""):
        assert extract_url_blocked(bad) is True, bad


def test_blocks_cloud_metadata_endpoint():
    assert _is_blocked_host("169.254.169.254") is True


def test_blocks_loopback_private_linklocal():
    for h in ("127.0.0.1", "10.0.0.5", "192.168.1.1", "172.16.0.1", "::1",
              "localhost", "0.0.0.0", "metadata.google.internal"):
        assert _is_blocked_host(h) is True, h


def test_allows_public_host():
    assert _is_blocked_host("example.com") is False
    assert _is_blocked_host("93.184.216.34") is False


def test_extract_rejects_private_url_before_request():
    out = extract("http://169.254.169.254/latest/meta-data/")
    assert out["success"] is False
    assert "SSRF" in out["error"] or "私网" in out["error"] or "169.254" in out["error"]


def test_extract_rejects_loopback_url():
    out = extract("http://127.0.0.1:8080/admin")
    assert out["success"] is False
