"""Internal documentation."""
from __future__ import annotations

from pathlib import Path

import pytest

from argos.sandbox.executor import select_backend


@pytest.fixture
def ex(tmp_path: Path, requires_sandbox):
    e = select_backend()()
    e.spawn(workspace=tmp_path, namespace={"__authorized_imports__": ["socket"]})
    yield e
    e.close()


def test_outbound_tcp_blocked(ex):
    code = (
        "import socket\n"
        "s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)\n"
        "s.settimeout(3)\n"
        "s.connect(('1.1.1.1', 53))\n"
        "'CONNECTED'"
    )
    r = ex.exec_code(code)
    assert not (r.ok and r.value_repr == "'CONNECTED'"), "外联竟成功——网络没真关!"
    assert r.exc != ""


def test_dns_resolution_blocked(ex):
    code = "import socket\nsocket.gethostbyname('example.com')"
    r = ex.exec_code(code)
    assert not r.ok, "DNS 解析竟成功——网络没真关!"
