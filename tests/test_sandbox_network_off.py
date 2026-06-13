"""Phase 3 铁证:沙箱内网络系统级 OFF(非 smolagents AST 限制)。
故意授权 socket import 让 AST 放行,断言【真连外网】被 OS 挡。
跑在有沙箱后端的平台(macOS Seatbelt / Linux bwrap/unshare);无后端时干净 skip。"""
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
    # 试图连 1.1.1.1:53 —— Seatbelt (deny network*) 必须挡住(抛 OSError/PermissionError)。
    code = (
        "import socket\n"
        "s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)\n"
        "s.settimeout(3)\n"
        "s.connect(('1.1.1.1', 53))\n"
        "'CONNECTED'"
    )
    r = ex.exec_code(code)
    assert not (r.ok and r.value_repr == "'CONNECTED'"), "外联竟成功——网络没真关!"
    # 应是异常(被沙箱拒),exc 非空。
    assert r.exc != ""


def test_dns_resolution_blocked(ex):
    code = "import socket\nsocket.gethostbyname('example.com')"
    r = ex.exec_code(code)
    assert not r.ok, "DNS 解析竟成功——网络没真关!"
