"""Phase 3:CapabilityBroker.request —— egress→审批→host 执行→签 Receipt→fail-closed(契约 §5)。"""
from __future__ import annotations

import asyncio

import pytest

from argos_agent.approval import ApprovalGate, ApprovalLevel
from argos_agent.sandbox.broker import BrokerResult, CapabilityBroker
from argos_agent.sandbox.egress import EgressPolicy
from argos_agent.tools.receipts import ReceiptSigner


def _broker(level=ApprovalLevel.AUTO, search_hosts=None):
    gate = ApprovalGate(level=level)
    egress = EgressPolicy(llm_hosts={"api.minimaxi.com"},
                          search_hosts=search_hosts or {"duckduckgo.com"}, mcp_hosts=set())
    signer = ReceiptSigner(key=b"host-only-key")
    return CapabilityBroker(gate=gate, egress=egress, signer=signer)


@pytest.mark.asyncio
async def test_run_command_auto_executes_and_signs():
    br = _broker(level=ApprovalLevel.AUTO)
    res = await br.request("run_command", {"command": "echo hi"})
    assert isinstance(res, str)
    assert "hi" in res and "exit_code=0" in res
    # 副产物:签了 Receipt(broker 暴露最近回执供 loop 投事件)
    rec = br.last_receipt
    assert rec is not None and rec.action == "run_command"
    assert br._signer.verify(rec) is True


@pytest.mark.asyncio
async def test_denied_returns_fail_closed_string_not_raise():
    br = _broker(level=ApprovalLevel.OBSERVE)  # OBSERVE → 一律 deny
    res = await br.request("run_command", {"command": "echo hi"})
    assert isinstance(res, str)
    assert "拒绝" in res    # fail-closed 拒绝串,不抛异常


@pytest.mark.asyncio
async def test_web_extract_egress_denied_host():
    br = _broker(level=ApprovalLevel.AUTO, search_hosts={"duckduckgo.com"})
    res = await br.request("web_extract", {"url": "https://evil.example.com/x"})
    assert "egress" in res or "不在允许" in res   # 越白名单 → 拒绝串


@pytest.mark.asyncio
async def test_unknown_action_rejected():
    br = _broker(level=ApprovalLevel.AUTO)
    res = await br.request("rm_rf_everything", {})
    assert "未知" in res or "不支持" in res


@pytest.mark.asyncio
async def test_broker_result_is_frozen_dataclass():
    """BrokerResult 是冻结 dataclass(契约 §5 不变量)。"""
    import dataclasses
    from argos_agent.tools.receipts import Receipt
    # 构造一个假 Receipt
    signer = ReceiptSigner(key=b"test")
    r = signer.sign(action="web_search", args={}, result="x", exit_code=None)
    br_result = BrokerResult(value="hello", receipt=r)
    assert dataclasses.is_dataclass(br_result)
    assert BrokerResult.__dataclass_params__.frozen is True
    assert br_result.value == "hello"
    assert br_result.receipt is r


@pytest.mark.asyncio
async def test_no_receipt_when_denied():
    """拒绝时 last_receipt 不被更新(不签名 = 无副作用回执)。"""
    br = _broker(level=ApprovalLevel.OBSERVE)
    old_receipt = br.last_receipt  # None 初始
    await br.request("run_command", {"command": "echo hi"})
    assert br.last_receipt is old_receipt  # 还是 None,未签
