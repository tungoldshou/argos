"""铁证④(spec §9 / §6):沙箱外泄防线 + egress fail-closed(可证伪,沙箱部分 macOS-only)。

诚实修正:Seatbelt profile 放宽 file-read*(读 ~/.ssh 允许,见 test_sandbox_fs_confinement),
故外泄向量是【越界写】+【网络】而非【读】。本铁证证:读到的密钥写不出 workspace;
网络出口 fail-closed —— web_search 锁定 provider 白名单,web_extract 放行任意【公网】host
但私网/回环/云元数据被 SSRF 硬挡(2026-06-18 用户拍板:出网问责靠 SSRF+每次签回执+审批拨盘,
不靠静态白名单 —— 否则 agent 连搜索结果页都打不开)。workspace 内合法 IO 正常。
若沙箱形同虚设(密钥能写出 / 能连内网元数据)→ 本测试红,纵深防线证伪。
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
async def test_broker_web_extract_blocks_internal_allows_public():
    """web_extract 出网策略(2026-06-18 用户拍板):目标 URL 由 agent 动态选 → 放行任意【公网】host,
    但私网/回环/保留/云元数据被 SSRF fail-closed 硬挡(不真发请求)。出网问责靠 SSRF(内网零信任)
    + 每次签 HMAC 回执 + 审批拨盘,不再靠静态白名单。web_search 的固定 provider 白名单不受影响。"""
    gate = ApprovalGate(level=ApprovalLevel.AUTO)
    egress = EgressPolicy(llm_hosts={"api.minimaxi.com"}, search_hosts={"duckduckgo.com"}, mcp_hosts=set())
    broker = CapabilityBroker(gate=gate, egress=egress, signer=ReceiptSigner(key=b"k"))
    # 私网/回环/云元数据 → SSRF fail-closed 拒(不真发请求、不签回执)
    for bad in ("http://169.254.169.254/latest/meta-data/", "http://127.0.0.1/admin",
                "http://10.0.0.5/x", "http://metadata.google.internal/"):
        out = await broker.request("web_extract", {"url": bad})
        assert isinstance(out, str) and ("SSRF" in out or "私网" in out or "内网" in out), bad
        assert broker.last_receipt is None, "被 SSRF 拒不签回执"
    # 公网 host → egress 层放行(只验裁决,不打真网;实际取页由 _http_get 逐跳再校验)
    assert broker._egress_deny_reason("web_extract", {"url": "https://news.example.com/a"}) is None
