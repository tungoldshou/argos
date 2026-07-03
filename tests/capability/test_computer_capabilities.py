from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from argos.approval import ApprovalGate, ApprovalLevel
from argos.capability import CapabilityRegistry, register_builtins
from argos.sandbox.broker import CapabilityBroker
from argos.sandbox.egress import EgressPolicy
from argos.tools.receipts import ReceiptSigner

_EXPECTED_COMPUTER_CAPS = (
    "computer_screenshot",
    "computer_click",
    "computer_double_click",
    "computer_type_text",
    "computer_key",
    "computer_scroll",
    "computer_open_app",
)


# ── helper ────────────────────────────────────────────────────────────────────

def _make_registry_with_builtins() -> CapabilityRegistry:
    reg = CapabilityRegistry()
    register_builtins(reg)
    return reg


def _make_broker(level: ApprovalLevel = ApprovalLevel.AUTO,
                 registry: CapabilityRegistry | None = None) -> CapabilityBroker:
    gate = ApprovalGate(level=level)
    egress = EgressPolicy(
        llm_hosts={"api.minimaxi.com"},
        search_hosts={"duckduckgo.com"},
        mcp_hosts=set(),
    )
    signer = ReceiptSigner(key=b"test-key-computer")
    return CapabilityBroker(
        gate=gate, egress=egress, signer=signer, registry=registry,
    )



def test_all_computer_caps_registered():
    reg = _make_registry_with_builtins()
    for name in _EXPECTED_COMPUTER_CAPS:
        assert name in reg, f"能力 {name!r} 未注册"


def test_computer_caps_count():
    reg = _make_registry_with_builtins()
    computer_caps = reg.by_kind("computer")
    assert len(computer_caps) == len(_EXPECTED_COMPUTER_CAPS), (
        f"computer 能力数量不匹配:实际={len(computer_caps)},期望={len(_EXPECTED_COMPUTER_CAPS)}\n"
        f"实际={[c.name for c in computer_caps]}"
    )



@pytest.mark.parametrize("name", _EXPECTED_COMPUTER_CAPS)
def test_computer_cap_kind_is_computer(name: str):
    reg = _make_registry_with_builtins()
    cap = reg.get(name)
    assert cap.kind == "computer", f"{name}: kind={cap.kind!r},期望 'computer'"


@pytest.mark.parametrize("name", _EXPECTED_COMPUTER_CAPS)
def test_computer_cap_risk_is_high(name: str):
    reg = _make_registry_with_builtins()
    cap = reg.get(name)
    assert cap.risk == "high", f"{name}: risk={cap.risk!r},期望 'high'"


@pytest.mark.parametrize("name", _EXPECTED_COMPUTER_CAPS)
def test_computer_cap_reversible_false(name: str):
    reg = _make_registry_with_builtins()
    cap = reg.get(name)
    assert cap.reversible is False, f"{name}: reversible={cap.reversible!r},期望 False"


@pytest.mark.parametrize("name", _EXPECTED_COMPUTER_CAPS)
def test_computer_cap_has_honest_verify_hint(name: str):
    reg = _make_registry_with_builtins()
    cap = reg.get(name)
    assert "GUI 动作无机检通道" in cap.verify_hint, (
        f"{name}: verify_hint={cap.verify_hint!r} 缺少诚实性声明"
    )
    assert "L5" in cap.verify_hint or "留痕" in cap.verify_hint, (
        f"{name}: verify_hint={cap.verify_hint!r} 缺少'L5 留痕'说明"
    )


def test_screenshot_verify_hint_contains_vlm_redline():
    reg = _make_registry_with_builtins()
    cap = reg.get("computer_screenshot")
    assert "screenshot 永不单独产出 passed" in cap.verify_hint, (
        f"computer_screenshot verify_hint 缺少 VLM 红线声明: {cap.verify_hint!r}"
    )


def test_computer_caps_visibility_all():
    reg = _make_registry_with_builtins()
    for name in _EXPECTED_COMPUTER_CAPS:
        cap = reg.get(name)
        assert cap.visibility == "all", f"{name}: visibility={cap.visibility!r},期望 'all'"



def test_computer_caps_in_risk_table():
    reg = _make_registry_with_builtins()
    table = reg.risk_table()
    for name in _EXPECTED_COMPUTER_CAPS:
        assert name in table, f"risk_table 缺少 {name!r}"
        assert table[name] == "high", f"risk_table[{name!r}]={table[name]!r},期望 'high'"



@pytest.mark.asyncio
async def test_computer_action_triggers_approval_request():
    reg = _make_registry_with_builtins()
    gate = ApprovalGate(level=ApprovalLevel.CONFIRM)
    egress = EgressPolicy(llm_hosts=set(), search_hosts=set(), mcp_hosts=set())
    signer = ReceiptSigner(key=b"key")

    approval_calls = []

    async def fake_gate_request(action, args, *, description="", risk="medium"):
        approval_calls.append({"action": action, "risk": risk})
        decision = MagicMock()
        decision.approved = False
        decision.reason = "test denial"
        return decision

    gate.request = fake_gate_request  # type: ignore[method-assign]

    broker = CapabilityBroker(gate=gate, egress=egress, signer=signer, registry=reg)
    result = await broker.request("computer_screenshot", {})

    assert approval_calls, "computer_screenshot 未触发审批(四线第一线缺失)"
    assert approval_calls[0]["action"] == "computer_screenshot"
    assert approval_calls[0]["risk"] == "high", (
        f"审批 risk 应为 high,得到 {approval_calls[0]['risk']!r}"
    )
    assert "拒绝" in result or "用户拒绝" in result


@pytest.mark.asyncio
async def test_computer_action_hmac_receipt_signed_on_approval():
    import os
    from argos.perception.executor import ComputerExecutor, ComputerActionResult

    reg = _make_registry_with_builtins()
    gate = ApprovalGate(level=ApprovalLevel.AUTO)
    egress = EgressPolicy(llm_hosts=set(), search_hosts=set(), mcp_hosts=set())
    signer = ReceiptSigner(key=b"key-receipt")

    async def auto_approve(action, args, *, description="", risk="medium"):
        decision = MagicMock()
        decision.approved = True
        decision.reason = ""
        return decision

    gate.request = auto_approve  # type: ignore[method-assign]

    broker = CapabilityBroker(gate=gate, egress=egress, signer=signer, registry=reg)

    fake_result = ComputerActionResult(
        ok=True,
        detail="截图成功(test stub)",
        artifact_path="/tmp/test_stub.png",
        size=(1920, 1080),
    )
    with patch.object(ComputerExecutor, "dispatch", return_value=fake_result),\
         patch.dict(os.environ, {"ARGOS_COMPUTER_USE": "1"}):
        await broker.request("computer_screenshot", {})

    receipt = broker.last_receipt
    assert receipt is not None, (
        "computer_screenshot 获批后未签 HMAC 回执(四线第二线缺失)\n"
        "提示:broker._execute 缺 computer.* 分支会导致此断言失败"
    )
    assert receipt.action == "computer_screenshot"
    assert signer.verify(receipt), "HMAC 回执签名校验失败(不可伪造性)"



@pytest.mark.parametrize("action", [
    "computer_screenshot",
    "computer_click",
    "computer_type_text",
    "computer_open_app",
])
def test_ledger_entry_for_computer_action_reversible_impossible(action: str):
    from argos.ledger.builder import build_entry

    signer = ReceiptSigner(key=b"k")
    receipt = signer.sign(
        action=action,
        args={},
        result="executed",
        exit_code=0,
    )

    entry = build_entry(
        receipt=receipt,
        run_id="test-run-p6a",
        seq=1,
        args={},
        undo_token=None,
    )

    assert entry.reversible == "no", (
        f"{action}: LedgerEntry.reversible 应为 'no',得到 {entry.reversible!r}\n"
        "提示:检查 ledger.builder._IRREVERSIBLE_ACTIONS 是否包含此 action"
    )
    assert entry.undo_state == "impossible", (
        f"{action}: LedgerEntry.undo_state 应为 'impossible',得到 {entry.undo_state!r}"
    )
    assert entry.risk == "high", (
        f"{action}: LedgerEntry.risk 应为 'high'(computer.* 全部高风险),得到 {entry.risk!r}"
    )



def test_register_builtins_computer_caps_idempotent():
    reg = CapabilityRegistry()
    register_builtins(reg)
    count_before = len(reg.by_kind("computer"))

    register_builtins(reg)
    count_after = len(reg.by_kind("computer"))

    assert count_before == count_after == len(_EXPECTED_COMPUTER_CAPS)
