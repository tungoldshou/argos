from __future__ import annotations

import asyncio

import pytest

from argos.approval import ApprovalGate, ApprovalLevel
from argos.i18n import t
from argos.sandbox.broker import BrokerResult, CapabilityBroker
from argos.sandbox.egress import EgressPolicy
from argos.tools.receipts import ReceiptSigner


def _broker(level=ApprovalLevel.AUTO, search_hosts=None):
    gate = ApprovalGate(level=level)
    egress = EgressPolicy(llm_hosts={"api.minimaxi.com"},
                          search_hosts=search_hosts or {"duckduckgo.com"}, mcp_hosts=set())
    signer = ReceiptSigner(key=b"host-only-key")
    return CapabilityBroker(gate=gate, egress=egress, signer=signer)


def test_broker_passes_workspace_to_run_command(monkeypatch, tmp_path):
    captured = {}

    def fake_run(command, *, workspace=None, allow_network=False):
        captured["workspace"] = workspace
        return ("ok", 0)

    monkeypatch.setattr("argos.tools.shell.run_command", fake_run)
    gate = ApprovalGate(level=ApprovalLevel.AUTO)
    egress = EgressPolicy(llm_hosts=set(), search_hosts=set(), mcp_hosts=set())
    broker = CapabilityBroker(gate=gate, egress=egress, signer=ReceiptSigner(key=b"k"),
                              workspace=tmp_path)
    broker._execute("run_command", {"command": "python app.py"})
    assert captured["workspace"] == tmp_path


def test_broker_workspace_defaults_none_back_compat(monkeypatch):
    captured = {}

    def fake_run(command, *, workspace=None, allow_network=False):
        captured["workspace"] = workspace
        return ("ok", 0)

    monkeypatch.setattr("argos.tools.shell.run_command", fake_run)
    gate = ApprovalGate(level=ApprovalLevel.AUTO)
    egress = EgressPolicy(llm_hosts=set(), search_hosts=set(), mcp_hosts=set())
    broker = CapabilityBroker(gate=gate, egress=egress, signer=ReceiptSigner(key=b"k"))
    broker._execute("run_command", {"command": "ls"})
    assert captured["workspace"] is None


@pytest.mark.asyncio
async def test_run_command_auto_runs_at_yolo():
    br = _broker(level=ApprovalLevel.AUTO)
    res = await br.request("run_command", {"command": "echo hi"})
    assert isinstance(res, str)
    assert "hi" in res and "exit_code=0" in res
    assert br._gate.pending() == [], "YOLO 下 run_command 不应挂起审批"
    rec = br.last_receipt
    assert rec is not None and rec.action == "run_command"
    assert br._signer.verify(rec) is True


@pytest.mark.asyncio
async def test_dangerous_run_command_still_blocked_at_yolo():
    br = _broker(level=ApprovalLevel.AUTO)
    res = await br.request("run_command", {"command": "rm -rf /"})
    assert isinstance(res, str)
    assert "拒绝" in res or "硬规则" in res or "deny" in res.lower() or "denied" in res.lower(), res
    assert br.last_receipt is None, "被硬规则拦的危险命令不应执行/签回执"


@pytest.mark.asyncio
async def test_denied_returns_fail_closed_string_not_raise():
    br = _broker(level=ApprovalLevel.OBSERVE)
    res = await br.request("run_command", {"command": "echo hi"})
    assert isinstance(res, str)
    assert "拒绝" in res or "denied" in res.lower()


@pytest.mark.asyncio
async def test_web_extract_allows_public_denies_internal():
    br = _broker(level=ApprovalLevel.AUTO, search_hosts={"duckduckgo.com"})
    assert br._egress_deny_reason("web_extract", {"url": "https://news.example.com/x"}) is None
    for bad in ("http://169.254.169.254/latest/meta-data/", "http://127.0.0.1:8080/admin",
                "http://10.0.0.5/", "http://metadata.google.internal/"):
        assert br._egress_deny_reason("web_extract", {"url": bad}) is not None, bad
    res = await br.request("web_extract", {"url": "http://169.254.169.254/"})
    assert "SSRF" in res or "私网" in res or "内网" in res
    assert br.last_receipt is None


@pytest.mark.asyncio
async def test_unknown_action_rejected():
    br = _broker(level=ApprovalLevel.AUTO)
    res = await br.request("rm_rf_everything", {})
    assert "未知" in res or "不支持" in res or "unknown" in res.lower() or "unsupported" in res.lower()


@pytest.mark.asyncio
async def test_broker_result_is_frozen_dataclass():
    import dataclasses
    from argos.tools.receipts import Receipt
    signer = ReceiptSigner(key=b"test")
    r = signer.sign(action="web_search", args={}, result="x", exit_code=None)
    br_result = BrokerResult(value="hello", receipt=r)
    assert dataclasses.is_dataclass(br_result)
    assert BrokerResult.__dataclass_params__.frozen is True
    assert br_result.value == "hello"
    assert br_result.receipt is r


@pytest.mark.asyncio
async def test_no_receipt_when_denied():
    br = _broker(level=ApprovalLevel.OBSERVE)
    old_receipt = br.last_receipt
    await br.request("run_command", {"command": "echo hi"})
    assert br.last_receipt is old_receipt


@pytest.mark.asyncio
async def test_web_search_egress_denied_when_provider_host_not_allowed(monkeypatch, tmp_path):
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)  # → DDGS provider, host=duckduckgo.com
    config_dir = tmp_path / "custom-config"
    monkeypatch.setenv("ARGOS_CONFIG_DIR", str(config_dir))
    br = _broker(level=ApprovalLevel.AUTO, search_hosts={"someother.example"})
    res = await br.request("web_search", {"query": "x"})
    assert "egress" in res or "不在允许" in res
    assert str(config_dir / "config.json") in res
    assert "~/.argos" not in res
    assert br.last_receipt is None


@pytest.mark.asyncio
async def test_web_search_egress_allowed_when_provider_host_listed(monkeypatch):
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)  # DDGS → duckduckgo.com

    import argos.web as _w
    monkeypatch.setattr(_w, "search", lambda q, limit=5: {
        "success": True, "results": [{"title": "t", "url": "u", "snippet": "s"}],
    })
    br = _broker(level=ApprovalLevel.AUTO, search_hosts={"duckduckgo.com"})
    res = await br.request("web_search", {"query": "x", "limit": 3})
    assert "egress" not in res and "不在允许" not in res
    assert br.last_receipt is not None and br.last_receipt.action == "web_search"


@pytest.mark.asyncio
async def test_network_action_denied_at_observe_through_request():
    br = _broker(level=ApprovalLevel.OBSERVE, search_hosts={"duckduckgo.com"})
    res = await br.request("web_search", {"query": "x"})
    assert "拒绝" in res or "denied" in res.lower()
    assert br.last_receipt is None


@pytest.mark.asyncio
async def test_take_receipt_returns_and_clears():
    br = _broker(level=ApprovalLevel.AUTO)
    await br.request("run_command", {"command": "echo hi"})
    assert br.last_receipt is not None
    rec = br.take_receipt()
    assert rec is not None and rec.action == "run_command"
    assert br.last_receipt is None
    assert br.take_receipt() is None


@pytest.mark.asyncio
async def test_egress_deny_message_does_not_mention_nonexistent_allow_command(monkeypatch):
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)
    br = _broker(level=ApprovalLevel.AUTO, search_hosts={"someother.example"})
    res = await br.request("web_search", {"query": "test"})
    assert "egress" in res or "不在允许" in res
    assert "/allow" not in res, f"错误消息引用了不存在的 /allow 命令:{res!r}"
    assert "/trust" in res or "config.json" in res, (
        f"消息未提供真实可用的补救途径:{res!r}"
    )


@pytest.mark.asyncio
async def test_egress_deny_reason_message_format(monkeypatch):
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)
    br = _broker(level=ApprovalLevel.AUTO, search_hosts={"someother.example"})
    reason = br._egress_deny_reason("web_search", {"query": "test"})
    assert reason is not None, "期望 egress 拒绝原因"
    assert "/allow" not in reason, f"拒绝理由引用了不存在的 /allow 命令:{reason!r}"
    assert "/trust" in reason or "config.json" in reason, (
        f"拒绝理由未提供真实可用的补救途径:{reason!r}"
    )


@pytest.mark.asyncio
async def test_run_command_not_force_confirmed_at_yolo():
    gate = ApprovalGate(level=ApprovalLevel.AUTO)
    egress = EgressPolicy(llm_hosts=set(), search_hosts={"duckduckgo.com"}, mcp_hosts=set())
    signer = ReceiptSigner(key=b"k")
    br = CapabilityBroker(gate=gate, egress=egress, signer=signer)

    seen = {}

    async def fake_request(action, args, *, description, risk, timeout=60.0):
        seen["level"] = gate.level
        from argos.approval import Decision
        return Decision(kind="once", reason="测试放行")

    gate.request = fake_request  # type: ignore[assignment]
    await br.request("run_command", {"command": "echo hi"})
    assert seen["level"] is ApprovalLevel.AUTO, "YOLO 下 run_command 不应被强制降 CONFIRM,应保持 AUTO 自动放行"
    assert gate.level is ApprovalLevel.AUTO, "裁决后档位不变"
