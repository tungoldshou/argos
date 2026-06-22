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


def test_cautious_auto_passes_sandboxed_run_command():
    """Phase 1(2026-06-20)「牢笼内自动跑」:Cautious(low_risk_auto)下 run_command(沙箱命令)
    自动放行 —— Seatbelt 关在牢笼里、网络 OFF、写caged;危险命令(rm -rf)仍在 hard_rule 步 deny。
    裸 CONFIRM(测试直建,无 trust 语义)不受影响,run_command 照旧 ask。"""
    from argos.permissions import get_config
    from argos.permissions.evaluator import evaluate
    cfg = get_config()

    def ev(action, args, low, risk="medium"):
        return evaluate(action, args, gate_level="confirm", config=cfg,
                        low_risk_auto=low, risk=risk).decision

    # Cautious:安全 run_command 自动放行,危险命令仍 deny
    assert ev("run_command", {"command": "pytest -q"}, low=True) == "approve"
    assert ev("run_command", {"command": "rm -rf /"}, low=True) == "deny"
    # 非沙箱中危(浏览器写/mcp)仍 ask —— 它们不在牢笼里
    assert ev("browser_click", {}, low=True) == "ask"
    assert ev("mcp_call", {}, low=True) == "ask"
    # 裸 CONFIRM(low_risk_auto=False):run_command 照旧 ask(不动既有 CONFIRM 语义)
    assert ev("run_command", {"command": "pytest -q"}, low=False) == "ask"


def test_build_components_default_gate_is_cautious(tmp_path, monkeypatch):
    """Phase 1:产品默认档(build_components,不传 approval_level)= Cautious —— gate.level=CONFIRM
    且 low_risk_auto ON(此前默认是裸 CONFIRM、low_risk_auto=False,导致开箱'啥都问')。"""
    import argos.app_factory as af
    monkeypatch.setenv("ARGOS_NO_DAEMON", "1")
    monkeypatch.setenv("ARGOS_DB_PATH", str(tmp_path / "argos.db"))
    monkeypatch.setenv("ARGOS_CONFIG_DIR", str(tmp_path / "cfg"))   # 空目录:走旧 env 回退,无 key 时 CI 不挂
    monkeypatch.setattr(af.config, "DEFAULT_KEYS", ["k-test"])      # 之前裸调 build_components(),靠开发机 key 才过
    from argos.app_factory import build_components
    c = build_components()
    assert c.gate.level is ApprovalLevel.CONFIRM
    assert getattr(c.gate, "_low_risk_auto", False) is True, "默认档应是 Cautious(low_risk_auto ON)"


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


def test_override_semantics_force_confirm_overrides_cautious_autopass():
    """review #4 修:strong-tier 强制确认(override=CONFIRM)真生效 —— 把 Cautious 牢笼自动放行的
    run_command 升格为 ask;pop 后还原。此前 loop._approval_level_override 只写不读(死写),
    强制确认形同虚设(spec §11 保证落空)。"""
    from argos.permissions.trust_dial import TrustLevel
    gate = ApprovalGate()
    gate.set_trust_level(TrustLevel.L1_DANGEROUS_ONLY)  # Cautious
    assert gate.evaluate_sync("run_command", {"command": "pytest -q"}).decision == "approve"
    snap = gate.push_override_semantics(ApprovalLevel.CONFIRM)
    assert gate.level is ApprovalLevel.CONFIRM and gate._low_risk_auto is False
    assert gate.evaluate_sync("run_command", {"command": "pytest -q"}).decision == "ask"
    gate.pop_override_semantics(snap)
    assert gate._low_risk_auto is True
    assert gate.evaluate_sync("run_command", {"command": "pytest -q"}).decision == "approve"


def test_override_semantics_accept_edits_loosens_to_cage_autopass():
    """approve_accept_edits(override=ACCEPT_EDITS)维持牢笼放行:从 paranoid(每步问)放宽到沙箱命令自动批。"""
    from argos.permissions.trust_dial import TrustLevel
    gate = ApprovalGate()
    gate.set_trust_level(TrustLevel.L0_EVERY_STEP)  # paranoid:连只读也问
    assert gate.evaluate_sync("run_command", {"command": "pytest -q"}).decision == "ask"
    snap = gate.push_override_semantics(ApprovalLevel.ACCEPT_EDITS)
    assert gate.evaluate_sync("run_command", {"command": "pytest -q"}).decision == "approve"
    gate.pop_override_semantics(snap)
    assert gate.evaluate_sync("run_command", {"command": "pytest -q"}).decision == "ask"


def test_loop_applies_override_around_exec_code():
    """review #4:loop 在 exec_code 前后 push/pop override 语义(把死写接通)。"""
    import inspect
    from argos.core.loop import AgentLoop
    src = inspect.getsource(AgentLoop._drive) if hasattr(AgentLoop, "_drive") else inspect.getsource(AgentLoop.run)
    # 源码里 act 段须引用 push_override_semantics(消费 _approval_level_override)
    full = inspect.getsource(AgentLoop)
    assert "push_override_semantics" in full
    assert "pop_override_semantics" in full
