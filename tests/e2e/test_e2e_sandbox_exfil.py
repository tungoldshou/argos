"""铁证④(spec §9 / §6):沙箱外泄防线 + egress fail-closed(可证伪,沙箱部分 macOS-only)。

诚实修正:Seatbelt profile 放宽 file-read*(读 ~/.ssh 允许,见 test_sandbox_fs_confinement),
故外泄向量是【越界写】+【网络】而非【读】。本铁证证:读到的密钥写不出 workspace、
非白名单网络被 broker fail-closed 拒;workspace 内合法 IO 正常。
若沙箱形同虚设(密钥能写出 / 能连任意外网)→ 本测试红,纵深防线证伪。
"""
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
    """诚实外泄防线:读密钥可能成功,但读到的东西【写不出 workspace】—— OS 斩断外泄向量。"""
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
    """合法 workspace 内读写正常(沙箱不是把一切都禁了)。"""
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
    """EgressPolicy(契约 §5):非白名单主机被拒,白名单(LLM 端点)放行,用户批准后加白。"""
    pol = EgressPolicy(llm_hosts={"api.minimaxi.com"}, search_hosts=set(), mcp_hosts=set())
    assert pol.allowed("https://api.minimaxi.com/anthropic") is True
    assert pol.allowed("https://evil.example.com/steal") is False
    pol.allow("evil.example.com")  # 用户批准后加白
    assert pol.allowed("https://evil.example.com/steal") is True


@pytest.mark.asyncio
async def test_broker_denies_network_to_non_allowlisted():
    """broker-gated web_extract 到非白名单域 → fail-closed 拒绝串(不真发请求,spec §6.4)。"""
    gate = ApprovalGate(level=ApprovalLevel.AUTO)
    egress = EgressPolicy(llm_hosts={"api.minimaxi.com"}, search_hosts={"duckduckgo.com"}, mcp_hosts=set())
    broker = CapabilityBroker(gate=gate, egress=egress, signer=ReceiptSigner(key=b"k"))
    out = await broker.request("web_extract", {"url": "https://evil.example.com/x"})
    assert isinstance(out, str)
    assert "egress" in out or "不在允许" in out  # 越白名单 → fail-closed 拒绝串(不真抓)
