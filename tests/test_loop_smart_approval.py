"""Loop 端到端:smart approval 实际拦截 + D5 锁铁证 + secret 触发 + backward-compat。

不调真 LLM,直接调 ApprovalGate.request(等同 loop 调用方式)。"""
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
    # teardown:重置 singleton,避免 soft-allow 等规则跨 test 串味
    # (否则 test_tui_approval 等后续 test 拿到残留 config,pytest 命令命中 ^pytest 软 allow 短路)
    _reset_config()
    _reset_audit()


# ── backward-compat(D20):无 permissions.json → 走 default_level ───
@pytest.mark.asyncio
async def test_no_config_uses_gate_level():
    gate = ApprovalGate(ApprovalLevel.AUTO)
    # 没 permissions.json → gate.level=AUTO 路径,直接 approve
    d = await gate.request("run_command", {"cmd": "ls -la"}, description="x", risk="low")
    assert d.approved is True
    assert d.kind == "once"


# ── D5 锁铁证 1:default_level=AUTO + 危险命令仍 deny ───────────
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


# ── D5 锁铁证 2:default_level=AUTO + soft allow `^rm ` + 危险命令仍 deny ──
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


# ── soft allow 短路:不查 level ─────────────────────────────────
@pytest.mark.asyncio
async def test_soft_allow_short_circuits_in_loop():
    from argos.permissions import config as _cfg
    Path(_cfg.CONFIG_PATH).write_text(json.dumps({
        "version": 1,
        "allow": [{"tool": "run_command", "matcher": r"^pytest"}],
    }))
    from argos.permissions import reload_config
    reload_config()
    gate = ApprovalGate(ApprovalLevel.CONFIRM)  # 即便 confirm 档
    d = await gate.request("run_command", {"cmd": "pytest -x"}, description="x", risk="low")
    assert d.approved is True
    assert d.kind == "once"


# ── 系统路径拒 ─────────────────────────────────────────────
@pytest.mark.asyncio
async def test_system_path_denied_in_loop():
    gate = ApprovalGate(ApprovalLevel.AUTO)
    d = await gate.request("write_file", {"path": "/etc/passwd", "content": "x"}, description="x", risk="high")
    assert d.approved is False
    assert d.kind == "deny"
    assert "/etc/" in d.reason or "system_path" in d.reason


# ── audit log 写:denied 也写(D17 锁) ─────────────────────────
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


# ── audit log 写:approved 也写 ─────────────────────────────
@pytest.mark.asyncio
async def test_audit_log_written_on_approve():
    from argos.permissions import audit as _audit
    gate = ApprovalGate(ApprovalLevel.AUTO)
    await gate.request("run_command", {"cmd": "ls -la"}, description="x", risk="low")
    files = list(_audit.AUDIT_DIR.glob("approvals-*.jsonl"))
    content = files[0].read_text()
    assert "auto" in content


# ── workspace 内允许文件 ────────────────────────────────────
@pytest.mark.asyncio
async def test_workspace_file_allowed_in_loop():
    """workspace 内文件不属系统路径 → 默认 AUTO 直接 approve。"""
    from pathlib import Path as P
    workspace = P("/tmp/argos_test_workspace")
    workspace.mkdir(exist_ok=True)
    gate = ApprovalGate(ApprovalLevel.AUTO)
    gate.set_workspace(str(workspace))
    test_file = workspace / "a.py"
    d = await gate.request("write_file", {"path": str(test_file), "content": "x"}, description="x", risk="low")
    assert d.approved is True
    assert d.kind == "once"
