"""Internal documentation."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from argos import config
from argos import jsonl_log

_log = logging.getLogger("argos.permissions.audit")

AUDIT_DIR: Path | None = None
RETAIN_DAYS: int = 30


def audit_dir(path: Path | None = None) -> Path:
    return Path(
        path or AUDIT_DIR or (
            Path(config.get("ARGOS_CONFIG_DIR") or (Path.home() / ".argos")).expanduser()
            / "audit"
        )
    )


def _file_for_date(d: datetime) -> Path:
    return audit_dir() / f"approvals-{d.strftime('%Y-%m-%d')}.jsonl"


@dataclass
class AuditLog:
    session_id: str

    def log(
        self,
        *,
        tool: str,
        args: str,
        decision: str,
        trigger: str,
        by: str,
        rule_name: str | None = None,
        secret_pattern: str | None = None,
        risk: str = "medium",
        session_id: str | None = None,
    ) -> None:
        row = {
            "ts": datetime.now().isoformat(timespec="milliseconds"),
            "session_id": session_id or self.session_id,
            "tool": tool,
            "args": args[:200] if isinstance(args, str) else str(args)[:200],
            "decision": decision,
            "trigger": trigger,
            "by": by,
            "rule_name": rule_name,
            "secret_pattern": secret_pattern,
            "risk": risk,
        }
        jsonl_log.append_line(_file_for_date(datetime.now()), row, logger=_log)

    def cleanup_old_logs(self, *, days: int = RETAIN_DAYS) -> int:
        """Internal documentation."""
        return jsonl_log.cleanup_files_by_name_date(
            audit_dir(), "approvals-*.jsonl",
            prefix="approvals-", days=days, logger=_log,
        )


_audit: AuditLog | None = None


def get_audit_log() -> AuditLog:
    global _audit
    if _audit is None:
        _audit = AuditLog(session_id="")
    return _audit


def _reset_audit() -> None:
    global _audit
    _audit = None
