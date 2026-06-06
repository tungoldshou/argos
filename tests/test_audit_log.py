"""Audit log 写 / 跨日 / 30 天清理 / IO 失败 continue(spec §2.7, D7 / D17 锁)。"""
from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from argos_agent.permissions.audit import AuditLog, AUDIT_DIR, RETAIN_DAYS


def test_audit_log_creates_dir(tmp_path, monkeypatch):
    p = tmp_path / "audit"
    monkeypatch.setattr("argos_agent.permissions.audit.AUDIT_DIR", p)
    log = AuditLog(session_id="s1")
    log.log(tool="x", args="y", decision="approved", trigger="level:auto", by="level", risk="low")
    assert p.exists()
    files = list(p.glob("approvals-*.jsonl"))
    assert len(files) == 1


def test_audit_log_appends_jsonl(tmp_path, monkeypatch):
    p = tmp_path / "audit"
    monkeypatch.setattr("argos_agent.permissions.audit.AUDIT_DIR", p)
    log = AuditLog(session_id="s1")
    log.log(tool="run_command", args="ls", decision="approved", trigger="soft_allow:^ls ", by="allowlist", risk="low")
    log.log(tool="run_command", args="rm -rf /", decision="denied", trigger="hard_rule:rm_rf_root", by="rule", risk="high")
    files = list(p.glob("approvals-*.jsonl"))
    assert len(files) == 1
    lines = files[0].read_text().strip().split("\n")
    assert len(lines) == 2
    obj1 = json.loads(lines[0])
    obj2 = json.loads(lines[1])
    assert obj1["tool"] == "run_command"
    assert obj2["decision"] == "denied"


def test_audit_log_io_failure_continues(tmp_path, monkeypatch):
    """写失败(模拟 OSError)→ log warning + 继续(不抛,spec §2.7)。"""
    p = tmp_path / "audit"
    monkeypatch.setattr("argos_agent.permissions.audit.AUDIT_DIR", p)
    log = AuditLog(session_id="s1")
    import builtins
    real_open = builtins.open

    def _broken(*a, **kw):
        if "approvals-" in str(a[0] if a else ""):
            raise OSError("disk full")
        return real_open(*a, **kw)
    monkeypatch.setattr("builtins.open", _broken)
    # 不抛(行为正确)
    log.log(tool="x", args="y", decision="approved", trigger="level:auto", by="level", risk="low")
    # 不抛即过(spec §2.7 锁)


def test_audit_log_secret_pattern_field(tmp_path, monkeypatch):
    p = tmp_path / "audit"
    monkeypatch.setattr("argos_agent.permissions.audit.AUDIT_DIR", p)
    log = AuditLog(session_id="s1")
    log.log(
        tool="write_file", args="a.py", decision="asked", trigger="secret:AWS access key",
        by="secret", secret_pattern="AWS access key", risk="high",
    )
    file = next(p.glob("approvals-*.jsonl"))
    obj = json.loads(file.read_text().strip())
    assert obj["secret_pattern"] == "AWS access key"


def test_audit_log_cleanup_old(tmp_path, monkeypatch):
    """30 天前文件启动时被删(D7 锁)。"""
    p = tmp_path / "audit"
    monkeypatch.setattr("argos_agent.permissions.audit.AUDIT_DIR", p)
    p.mkdir()
    old_date = (datetime.now() - timedelta(days=31)).strftime("%Y-%m-%d")
    new_date = datetime.now().strftime("%Y-%m-%d")
    (p / f"approvals-{old_date}.jsonl").write_text("old\n")
    (p / f"approvals-{new_date}.jsonl").write_text("new\n")
    log = AuditLog(session_id="s1")
    log.cleanup_old_logs(days=30)
    assert not (p / f"approvals-{old_date}.jsonl").exists()
    assert (p / f"approvals-{new_date}.jsonl").exists()


def test_audit_log_user_deny_by_field(tmp_path, monkeypatch):
    """用户手动 deny 时 by='user'。"""
    p = tmp_path / "audit"
    monkeypatch.setattr("argos_agent.permissions.audit.AUDIT_DIR", p)
    log = AuditLog(session_id="s1")
    log.log(tool="x", args="y", decision="denied", trigger="manual:1", by="user", risk="high")
    obj = json.loads(next(p.glob("approvals-*.jsonl")).read_text().strip())
    assert obj["by"] == "user"


def test_audit_log_schema_fields(tmp_path, monkeypatch):
    """audit row 字段全(必填 + 可选)。"""
    p = tmp_path / "audit"
    monkeypatch.setattr("argos_agent.permissions.audit.AUDIT_DIR", p)
    log = AuditLog(session_id="s1")
    log.log(
        tool="run_command", args="rm -rf /", decision="denied",
        trigger="hard_rule:rm_rf_root", by="rule", risk="high",
    )
    obj = json.loads(next(p.glob("approvals-*.jsonl")).read_text().strip())
    # 必填字段
    for k in ("ts", "session_id", "tool", "args", "decision", "trigger", "by", "risk"):
        assert k in obj
    assert obj["ts"].endswith("Z") is False  # ISO 8601 with ms, no Z (local time)


def test_audit_log_retain_days_default():
    """D7 锁:30 天保留期。"""
    assert RETAIN_DAYS == 30
