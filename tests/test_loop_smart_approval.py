"""Internal documentation."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from argos.approval import ApprovalGate, ApprovalLevel


@pytest.fixture(autouse=True)
def _reset(tmp_path, monkeypatch):
    from argos.permissions import config as _cfg
    from argos.permissions import audit as _audit
    monkeypatch.setattr(_cfg, "CONFIG_PATH", tmp_path / "permissions.json")
    monkeypatch.setattr(_audit, "AUDIT_DIR", tmp_path / "audit")
    from argos.permissions import _reset_config, _reset_audit
    _reset_config()
    _reset_audit()
    yield
    _reset_config()
    _reset_audit()


@pytest.mark.asyncio
async def test_no_config_uses_gate_level():
    gate = ApprovalGate(ApprovalLevel.AUTO)
    d = await gate.request("run_command", {"cmd": "ls -la"}, description="x", risk="low")
    assert d.approved is True
    assert d.kind == "once"


@pytest.mark.asyncio
async def test_d5_default_auto_still_deny_dangerous():
    from argos.permissions import config as _cfg
    Path(_cfg.CONFIG_PATH).write_text(json.dumps({"version": 1, "default_level": "auto"}))
    from argos.permissions import reload_config
    reload_config()
    gate = ApprovalGate(ApprovalLevel.AUTO)
    d = await gate.request("run_command", {"cmd": "rm -rf /"}, description="x", risk="high")
    assert d.approved is False
    assert d.kind == "deny"
    assert "rm_rf_root" in d.reason or "hard_rule" in d.reason


@pytest.mark.asyncio
async def test_d5_soft_allow_cannot_bypass_hard_rule():
    from argos.permissions import config as _cfg
    Path(_cfg.CONFIG_PATH).write_text(json.dumps({
        "version": 1,
        "default_level": "auto",
        "allow": [{"tool": "run_command", "matcher": r"^rm "}],
    }))
    from argos.permissions import reload_config
    reload_config()
    gate = ApprovalGate(ApprovalLevel.AUTO)
    d = await gate.request("run_command", {"cmd": "rm -rf /"}, description="x", risk="high")
    assert d.approved is False
    assert d.kind == "deny"
    assert "rm_rf_root" in d.reason or "hard_rule" in d.reason


@pytest.mark.asyncio
async def test_soft_allow_short_circuits_in_loop():
    from argos.permissions import config as _cfg
    Path(_cfg.CONFIG_PATH).write_text(json.dumps({
        "version": 1,
        "allow": [{"tool": "run_command", "matcher": r"^pytest"}],
    }))
    from argos.permissions import reload_config
    reload_config()
    gate = ApprovalGate(ApprovalLevel.CONFIRM)
    d = await gate.request("run_command", {"cmd": "pytest -x"}, description="x", risk="low")
    assert d.approved is True
    assert d.kind == "once"


@pytest.mark.asyncio
async def test_system_path_denied_in_loop():
    gate = ApprovalGate(ApprovalLevel.AUTO)
    d = await gate.request("write_file", {"path": "/etc/passwd", "content": "x"}, description="x", risk="high")
    assert d.approved is False
    assert d.kind == "deny"
    assert "/etc/" in d.reason or "system_path" in d.reason


@pytest.mark.asyncio
async def test_audit_log_written_on_deny():
    from argos.permissions import audit as _audit
    gate = ApprovalGate(ApprovalLevel.AUTO)
    await gate.request("run_command", {"cmd": "rm -rf /"}, description="x", risk="high")
    files = list(_audit.AUDIT_DIR.glob("approvals-*.jsonl"))
    assert len(files) >= 1
    content = files[0].read_text()
    assert "rm_rf_root" in content
    assert "denied" in content


@pytest.mark.asyncio
async def test_audit_log_written_on_approve():
    from argos.permissions import audit as _audit
    gate = ApprovalGate(ApprovalLevel.AUTO)
    await gate.request("run_command", {"cmd": "ls -la"}, description="x", risk="low")
    files = list(_audit.AUDIT_DIR.glob("approvals-*.jsonl"))
    content = files[0].read_text()
    assert "auto" in content


@pytest.mark.asyncio
async def test_workspace_file_allowed_in_loop():
    """Internal documentation."""
    from pathlib import Path as P
    workspace = P("/tmp/argos_test_workspace")
    workspace.mkdir(exist_ok=True)
    gate = ApprovalGate(ApprovalLevel.AUTO)
    gate.set_workspace(str(workspace))
    test_file = workspace / "a.py"
    d = await gate.request("write_file", {"path": str(test_file), "content": "x"}, description="x", risk="low")
    assert d.approved is True
    assert d.kind == "once"
