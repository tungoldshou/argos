"""tests/capability/test_computer_capabilities.py — computer.* 能力注册四线管辖验收测试。

验收规则(任务2 §1):
  1. register_builtins 后,所有 computer.* 能力均在 registry 中。
  2. 所有 computer.* 能力 kind="computer", risk="high", reversible=False。
  3. verify_hint 诚实写"GUI 动作无机检通道,验证走 L5 留痕"。
  4. computer.screenshot 的 verify_hint 含"screenshot 永不单独产出 passed"(红线)。
  5. 四线管辖:computer 动作经 broker.request → 审批触发(high 档) → HMAC 回执 → Ledger
     reversible=no/undo_state=impossible。
"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from argos.approval import ApprovalGate, ApprovalLevel
from argos.capability import CapabilityRegistry, register_builtins
from argos.sandbox.broker import CapabilityBroker
from argos.sandbox.egress import EgressPolicy
from argos.tools.receipts import ReceiptSigner

# 所有预期的 computer.* 能力名
_EXPECTED_COMPUTER_CAPS = (
    "computer.screenshot",
    "computer.click",
    "computer.double_click",
    "computer.type_text",
    "computer.key",
    "computer.scroll",
    "computer.open_app",
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


# ── 1. 能力注册完整性 ──────────────────────────────────────────────────────────

def test_all_computer_caps_registered():
    """register_builtins 后所有 computer.* 能力均已注册。"""
    reg = _make_registry_with_builtins()
    for name in _EXPECTED_COMPUTER_CAPS:
        assert name in reg, f"能力 {name!r} 未注册"


def test_computer_caps_count():
    """computer.* 能力数量与预期一致(防遗漏/多余)。"""
    reg = _make_registry_with_builtins()
    computer_caps = reg.by_kind("computer")
    assert len(computer_caps) == len(_EXPECTED_COMPUTER_CAPS), (
        f"computer 能力数量不匹配:实际={len(computer_caps)},期望={len(_EXPECTED_COMPUTER_CAPS)}\n"
        f"实际={[c.name for c in computer_caps]}"
    )


# ── 2. 能力 manifest 字段校验 ─────────────────────────────────────────────────

@pytest.mark.parametrize("name", _EXPECTED_COMPUTER_CAPS)
def test_computer_cap_kind_is_computer(name: str):
    """所有 computer.* 能力 kind='computer'。"""
    reg = _make_registry_with_builtins()
    cap = reg.get(name)
    assert cap.kind == "computer", f"{name}: kind={cap.kind!r},期望 'computer'"


@pytest.mark.parametrize("name", _EXPECTED_COMPUTER_CAPS)
def test_computer_cap_risk_is_high(name: str):
    """所有 computer.* 能力 risk='high'(屏幕/鼠标是全局资源,治理等级高)。"""
    reg = _make_registry_with_builtins()
    cap = reg.get(name)
    assert cap.risk == "high", f"{name}: risk={cap.risk!r},期望 'high'"


@pytest.mark.parametrize("name", _EXPECTED_COMPUTER_CAPS)
def test_computer_cap_reversible_false(name: str):
    """所有 computer.* 能力 reversible=False(GUI 动作不假装可撤销)。"""
    reg = _make_registry_with_builtins()
    cap = reg.get(name)
    assert cap.reversible is False, f"{name}: reversible={cap.reversible!r},期望 False"


@pytest.mark.parametrize("name", _EXPECTED_COMPUTER_CAPS)
def test_computer_cap_has_honest_verify_hint(name: str):
    """verify_hint 包含'GUI 动作无机检通道,验证走 L5 留痕'(诚实性声明)。"""
    reg = _make_registry_with_builtins()
    cap = reg.get(name)
    assert "GUI 动作无机检通道" in cap.verify_hint, (
        f"{name}: verify_hint={cap.verify_hint!r} 缺少诚实性声明"
    )
    assert "L5" in cap.verify_hint or "留痕" in cap.verify_hint, (
        f"{name}: verify_hint={cap.verify_hint!r} 缺少'L5 留痕'说明"
    )


def test_screenshot_verify_hint_contains_vlm_redline():
    """computer.screenshot 的 verify_hint 必须含 VLM 红线声明。"""
    reg = _make_registry_with_builtins()
    cap = reg.get("computer.screenshot")
    assert "screenshot 永不单独产出 passed" in cap.verify_hint, (
        f"computer.screenshot verify_hint 缺少 VLM 红线声明: {cap.verify_hint!r}"
    )


def test_computer_caps_visibility_all():
    """所有 computer.* 能力 visibility='all'(对所有用户可见)。"""
    reg = _make_registry_with_builtins()
    for name in _EXPECTED_COMPUTER_CAPS:
        cap = reg.get(name)
        assert cap.visibility == "all", f"{name}: visibility={cap.visibility!r},期望 'all'"


# ── 3. risk_table 暴露 high 风险 ──────────────────────────────────────────────

def test_computer_caps_in_risk_table():
    """register_builtins 后,risk_table() 包含所有 computer.* 能力且均为 high。"""
    reg = _make_registry_with_builtins()
    table = reg.risk_table()
    for name in _EXPECTED_COMPUTER_CAPS:
        assert name in table, f"risk_table 缺少 {name!r}"
        assert table[name] == "high", f"risk_table[{name!r}]={table[name]!r},期望 'high'"


# ── 4. 四线管辖:broker → 审批触发(high 档) ───────────────────────────────────

@pytest.mark.asyncio
async def test_computer_action_triggers_approval_request():
    """computer.* 动作经 broker.request → 审批触发(高风险,不静默执行)。

    AutoLevel 下 computer.* 仍需审批(verify:high risk → gate.request 被调用)。
    """
    reg = _make_registry_with_builtins()
    gate = ApprovalGate(level=ApprovalLevel.CONFIRM)
    egress = EgressPolicy(llm_hosts=set(), search_hosts=set(), mcp_hosts=set())
    signer = ReceiptSigner(key=b"key")

    # 劫持 gate.request 验证被调用
    approval_calls = []

    async def fake_gate_request(action, args, *, description="", risk="medium"):
        approval_calls.append({"action": action, "risk": risk})
        # 返回 denied decision(避免真执行 subprocess)
        decision = MagicMock()
        decision.approved = False
        decision.reason = "test denial"
        return decision

    gate.request = fake_gate_request  # type: ignore[method-assign]

    broker = CapabilityBroker(gate=gate, egress=egress, signer=signer, registry=reg)
    result = await broker.request("computer.screenshot", {})

    # 审批被调用(四线第一线)
    assert approval_calls, "computer.screenshot 未触发审批(四线第一线缺失)"
    assert approval_calls[0]["action"] == "computer.screenshot"
    assert approval_calls[0]["risk"] == "high", (
        f"审批 risk 应为 high,得到 {approval_calls[0]['risk']!r}"
    )
    # 拒绝后返回拒绝串(不抛异常)
    assert "拒绝" in result or "用户拒绝" in result


@pytest.mark.asyncio
async def test_computer_action_hmac_receipt_signed_on_approval():
    """computer.* 动作获批后:签 HMAC 回执(四线第二线)。

    修复:不再 mock broker._execute —— 那样会掩盖执行线真实断链。
    改为 patch ComputerExecutor.dispatch(避免真系统调用),验证完整管线:
      broker.request → 审批 → _execute → ComputerExecutor.dispatch → signer.sign → last_receipt
    """
    import os
    from argos.perception.executor import ComputerExecutor, ComputerActionResult

    reg = _make_registry_with_builtins()
    gate = ApprovalGate(level=ApprovalLevel.AUTO)
    egress = EgressPolicy(llm_hosts=set(), search_hosts=set(), mcp_hosts=set())
    signer = ReceiptSigner(key=b"key-receipt")

    # 劫持审批:自动批准(避免交互弹窗)
    async def auto_approve(action, args, *, description="", risk="medium"):
        decision = MagicMock()
        decision.approved = True
        decision.reason = ""
        return decision

    gate.request = auto_approve  # type: ignore[method-assign]

    broker = CapabilityBroker(gate=gate, egress=egress, signer=signer, registry=reg)

    # 劫持 ComputerExecutor.dispatch 避免真系统调用,但保留 broker._execute 真实路径。
    # 这样才能验证:执行线(computer.* 分支)→ dispatch → 回 result → signer.sign 全链路。
    fake_result = ComputerActionResult(
        ok=True,
        detail="截图成功(test stub)",
        artifact_path="/tmp/test_stub.png",
        size=(1920, 1080),
    )
    with patch.object(ComputerExecutor, "dispatch", return_value=fake_result), \
         patch.dict(os.environ, {"ARGOS_COMPUTER_USE": "1"}):
        await broker.request("computer.screenshot", {})

    receipt = broker.last_receipt
    assert receipt is not None, (
        "computer.screenshot 获批后未签 HMAC 回执(四线第二线缺失)\n"
        "提示:broker._execute 缺 computer.* 分支会导致此断言失败"
    )
    assert receipt.action == "computer.screenshot"
    # 验证签名有效(不可伪造性)
    assert signer.verify(receipt), "HMAC 回执签名校验失败(不可伪造性)"


# ── 5. Ledger 条目:reversible=no / undo_state=impossible ─────────────────────

@pytest.mark.parametrize("action", [
    "computer.screenshot",
    "computer.click",
    "computer.type_text",
    "computer.open_app",
])
def test_ledger_entry_for_computer_action_reversible_impossible(action: str):
    """computer.* 动作 → build_entry 自动分类 reversible='no'/undo_state='impossible'。

    使用 ledger.builder.build_entry(生产路径),验证 _IRREVERSIBLE_ACTIONS 中包含
    computer.* 并触发正确的可逆性/undo_state 推断(账本诚实性)。
    不依赖 daemon.registry.LedgerEntry.from_receipt,避免 pytest.skip 逃逸。
    """
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


# ── 6. 幂等注册 ───────────────────────────────────────────────────────────────

def test_register_builtins_computer_caps_idempotent():
    """register_builtins 幂等:二次调用不重复注册 computer.* 能力。"""
    reg = CapabilityRegistry()
    register_builtins(reg)
    count_before = len(reg.by_kind("computer"))

    # 二次调用不抛,也不增加数量
    register_builtins(reg)
    count_after = len(reg.by_kind("computer"))

    assert count_before == count_after == len(_EXPECTED_COMPUTER_CAPS)
