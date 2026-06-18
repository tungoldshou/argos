"""Phase 3:ApprovalLevel 4 档 + 契约 §6.3 Decision + ApprovalGate.respond 速选。"""
from __future__ import annotations

import asyncio

import pytest

from argos.approval import ApprovalGate, ApprovalLevel, Decision


def test_approval_levels():
    # Plan mode spec §2.5 选项 2 (approve and accept edits) → ACCEPT_EDITS 档(临时切 act 阶段
    # 写/编辑工具自动批,act 完恢复)。原 4 档不变 + 这一档;枚举值集合断言需含。
    assert {l.value for l in ApprovalLevel} == {
        "observe", "propose", "confirm", "auto", "accept_edits",
    }


def test_decision_kind_and_approved():
    assert Decision(kind="deny").approved is False
    assert Decision(kind="once").approved is True
    assert Decision(kind="session").approved is True
    assert Decision(kind="always").approved is True


def test_l1_low_risk_auto_approve_evaluator():
    """L1「只有危险操作才问」(2026-06-18 修):评估器默认决策处对【低危】动作自动放行,中/高危仍 ask。
    仅 low_risk_auto=True(trust dial L1 置)时生效;普通 CONFIRM(False)低危照旧 ask(行为不变)。"""
    from argos.permissions import get_config
    from argos.permissions.evaluator import evaluate
    cfg = get_config()
    low = evaluate("web_search", {"query": "x"}, gate_level="confirm", config=cfg,
                   low_risk_auto=True, risk="low")
    assert low.decision == "approve", low
    med = evaluate("write_file", {"path": "a.txt", "content": "x"}, gate_level="confirm",
                   config=cfg, low_risk_auto=True, risk="medium")
    assert med.decision == "ask", med
    plain = evaluate("web_search", {"query": "x"}, gate_level="confirm", config=cfg,
                     low_risk_auto=False, risk="low")
    assert plain.decision == "ask", plain


@pytest.mark.asyncio
async def test_gate_l1_auto_approves_low_risk_no_prompt():
    """gate.set_trust_level(L1) 后,低危动作经 request() 直接放行、不挂起(查天气这类免打扰)。"""
    from argos.permissions.trust_dial import TrustLevel
    gate = ApprovalGate()
    gate.set_trust_level(TrustLevel.L1_DANGEROUS_ONLY)
    dec = await gate.request("web_search", {"query": "成都天气"},
                             description="联网搜索", risk="low", timeout=0.5)
    assert dec.approved is True, dec
    assert gate.pending() == [], "L1 低危动作不应挂起审批(应自动放行)"


@pytest.mark.asyncio
async def test_request_then_respond_once():
    gate = ApprovalGate(level=ApprovalLevel.CONFIRM)

    async def driver():
        # 等请求挂上后,用 respond 速选 once 放行
        await asyncio.sleep(0.05)
        pend = gate.pending()
        assert len(pend) == 1
        assert gate.respond(pend[0].call_id, "once") is True

    task = asyncio.create_task(driver())
    dec = await gate.request("run_command", {"command": "pytest -q"},
                             description="执行命令 pytest -q", risk="medium", timeout=2.0)
    await task
    assert dec.approved is True
    assert dec.kind == "once"


@pytest.mark.asyncio
async def test_timeout_fail_closed_deny():
    gate = ApprovalGate(level=ApprovalLevel.CONFIRM)
    dec = await gate.request("git_push", {}, description="推送", risk="high", timeout=0.1)
    assert dec.approved is False   # 超时默认拒绝


@pytest.mark.asyncio
async def test_auto_level_auto_approves():
    gate = ApprovalGate(level=ApprovalLevel.AUTO)
    dec = await gate.request("run_command", {"command": "ls"},
                             description="列目录", risk="low", timeout=0.1)
    assert dec.approved is True    # AUTO 档放手,不等用户


@pytest.mark.asyncio
async def test_session_decision_caches():
    gate = ApprovalGate(level=ApprovalLevel.CONFIRM)

    async def driver():
        await asyncio.sleep(0.05)
        gate.respond(gate.pending()[0].call_id, "session")

    asyncio.create_task(driver())
    d1 = await gate.request("web_search", {"query": "x"}, description="搜 x", risk="low", timeout=2.0)
    assert d1.kind == "session"
    # 同 action+args 第二次:session 缓存命中,立即放行(不再挂起)
    d2 = await gate.request("web_search", {"query": "x"}, description="搜 x", risk="low", timeout=0.2)
    assert d2.approved is True
