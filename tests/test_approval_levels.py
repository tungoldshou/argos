"""Internal documentation."""
from __future__ import annotations

import asyncio

import pytest

from argos.approval import ApprovalGate, ApprovalLevel, Decision


def test_approval_levels():
    assert {l.value for l in ApprovalLevel} == {
        "observe", "propose", "confirm", "auto", "accept_edits",
    }


def test_decision_kind_and_approved():
    assert Decision(kind="deny").approved is False
    assert Decision(kind="once").approved is True
    assert Decision(kind="session").approved is True
    assert Decision(kind="always").approved is True


def test_l1_low_risk_auto_approve_evaluator():
    """Internal documentation."""
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
    """Internal documentation."""
    from argos.permissions import get_config
    from argos.permissions.evaluator import evaluate
    cfg = get_config()

    def ev(action, args, low, risk="medium"):
        return evaluate(action, args, gate_level="confirm", config=cfg,
                        low_risk_auto=low, risk=risk).decision

    assert ev("run_command", {"command": "pytest -q"}, low=True) == "approve"
    assert ev("run_command", {"command": "rm -rf /"}, low=True) == "deny"
    assert ev("browser_click", {}, low=True) == "ask"
    assert ev("mcp_call", {}, low=True) == "ask"
    assert ev("run_command", {"command": "pytest -q"}, low=False) == "ask"


def test_build_components_default_gate_is_cautious(tmp_path, monkeypatch):
    """Internal documentation."""
    import argos.app_factory as af
    monkeypatch.setenv("ARGOS_NO_DAEMON", "1")
    monkeypatch.setenv("ARGOS_DB_PATH", str(tmp_path / "argos.db"))
    monkeypatch.setenv("ARGOS_CONFIG_DIR", str(tmp_path / "cfg"))
    monkeypatch.setattr(af.config, "DEFAULT_KEYS", ["k-test"])
    from argos.app_factory import build_components
    c = build_components()
    assert c.gate.level is ApprovalLevel.CONFIRM
    assert getattr(c.gate, "_low_risk_auto", False) is True, "默认档应是 Cautious(low_risk_auto ON)"


@pytest.mark.asyncio
async def test_gate_l1_auto_approves_low_risk_no_prompt():
    """Internal documentation."""
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
    assert dec.approved is False


@pytest.mark.asyncio
async def test_auto_level_auto_approves():
    gate = ApprovalGate(level=ApprovalLevel.AUTO)
    dec = await gate.request("run_command", {"command": "ls"},
                             description="列目录", risk="low", timeout=0.1)
    assert dec.approved is True


@pytest.mark.asyncio
async def test_session_decision_caches():
    gate = ApprovalGate(level=ApprovalLevel.CONFIRM)

    async def driver():
        await asyncio.sleep(0.05)
        gate.respond(gate.pending()[0].call_id, "session")

    asyncio.create_task(driver())
    d1 = await gate.request("web_search", {"query": "x"}, description="搜 x", risk="low", timeout=2.0)
    assert d1.kind == "session"
    d2 = await gate.request("web_search", {"query": "x"}, description="搜 x", risk="low", timeout=0.2)
    assert d2.approved is True


def test_override_semantics_force_confirm_overrides_cautious_autopass():
    """Internal documentation."""
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
    """Internal documentation."""
    from argos.permissions.trust_dial import TrustLevel
    gate = ApprovalGate()
    gate.set_trust_level(TrustLevel.L0_EVERY_STEP)
    assert gate.evaluate_sync("run_command", {"command": "pytest -q"}).decision == "ask"
    snap = gate.push_override_semantics(ApprovalLevel.ACCEPT_EDITS)
    assert gate.evaluate_sync("run_command", {"command": "pytest -q"}).decision == "approve"
    gate.pop_override_semantics(snap)
    assert gate.evaluate_sync("run_command", {"command": "pytest -q"}).decision == "ask"


def test_loop_applies_override_around_exec_code():
    """Internal documentation."""
    import inspect
    from argos.core.loop import AgentLoop
    src = inspect.getsource(AgentLoop._drive) if hasattr(AgentLoop, "_drive") else inspect.getsource(AgentLoop.run)
    full = inspect.getsource(AgentLoop)
    assert "push_override_semantics" in full
    assert "pop_override_semantics" in full
