import sys
from pathlib import Path

import pytest

from argos.approval import ApprovalGate, ApprovalLevel
from argos.sandbox.broker import CapabilityBroker
from argos.sandbox.egress import EgressPolicy
from argos.sandbox.executor import SeatbeltExecutor
from argos.tools.receipts import ReceiptSigner

darwin_only = pytest.mark.skipif(
    sys.platform != "darwin",
    reason="Seatbelt(sandbox-exec)仅 macOS;Linux 后端(bubblewrap)留 roadmap(spec §6.3)",
)


@darwin_only
def test_sandbox_cannot_exfiltrate_secret_via_out_of_workspace_write(in_project):
    ex = SeatbeltExecutor()
    ex.spawn(workspace=in_project, namespace={"__authorized_imports__": ["pathlib"]})
    try:
        code = (
            "import pathlib\n"
            "secret = 'PRETEND-PRIVATE-KEY'\n"
            "out = pathlib.Path.home() / '.argos_exfil_probe'\n"
            "out.write_text(secret)\n"
            "'EXFILTRATED'"
        )
        r = ex.exec_code(code)
        assert not (r.ok and r.value_repr == "'EXFILTRATED'"), "密钥竟写出了 workspace —— 外泄向量没斩断!"
        assert (Path.home() / ".argos_exfil_probe").exists() is False
    finally:
        ex.close()


@darwin_only
def test_sandbox_allows_workspace_io(in_project):
    ex = SeatbeltExecutor()
    ex.spawn(workspace=in_project, namespace={"__authorized_imports__": ["pathlib"]})
    try:
        r = ex.exec_code(
            "import pathlib\n"
            "p = pathlib.Path('inside.txt')\n"
            "p.write_text('ok')\n"
            "p.read_text()"
        )
        assert r.ok, f"workspace 内合法 IO 应成功:{r.exc}"
        assert "ok" in r.value_repr
        assert (in_project / "inside.txt").exists()
    finally:
        ex.close()


def test_egress_policy_denies_non_allowlisted_host():
    pol = EgressPolicy(llm_hosts={"api.minimaxi.com"}, search_hosts=set(), mcp_hosts=set())
    assert pol.allowed("https://api.minimaxi.com/anthropic") is True
    assert pol.allowed("https://evil.example.com/steal") is False
    pol.allow("evil.example.com")
    assert pol.allowed("https://evil.example.com/steal") is True


@pytest.mark.asyncio
async def test_broker_web_extract_blocks_internal_allows_public():
    gate = ApprovalGate(level=ApprovalLevel.AUTO)
    egress = EgressPolicy(llm_hosts={"api.minimaxi.com"}, search_hosts={"duckduckgo.com"}, mcp_hosts=set())
    broker = CapabilityBroker(gate=gate, egress=egress, signer=ReceiptSigner(key=b"k"))
    for bad in ("http://169.254.169.254/latest/meta-data/", "http://127.0.0.1/admin",
                "http://10.0.0.5/x", "http://metadata.google.internal/"):
        out = await broker.request("web_extract", {"url": bad})
        assert isinstance(out, str) and ("SSRF" in out or "私网" in out or "内网" in out), bad
        assert broker.last_receipt is None, "被 SSRF 拒不签回执"
    assert broker._egress_deny_reason("web_extract", {"url": "https://news.example.com/a"}) is None
