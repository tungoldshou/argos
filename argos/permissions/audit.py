"""AuditLog:append-only JSONL,30 天滚动清理,IO 失败 continue(spec §2.7)。

任务:抽 jsonl_log 共享 best-effort 写入样板 —— `log()` 调 `jsonl_log.append_line`,
`cleanup_old_logs` 调 `jsonl_log.cleanup_files_by_name_date`。audit 专属的字段构造
(row schema) + `AuditLog` dataclass + 单例(get_audit_log) 留在本文件。
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from argos import jsonl_log

_log = logging.getLogger("argos.permissions.audit")

AUDIT_DIR: Path = Path(os.path.expanduser("~/.argos/audit"))
RETAIN_DAYS: int = 30


def _file_for_date(d: datetime) -> Path:
    return AUDIT_DIR / f"approvals-{d.strftime('%Y-%m-%d')}.jsonl"


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
        # 任务:抽 jsonl_log 助手 —— IO 失败 best-effort log warning 不抛,
        # 行为与原 _ensure_dir + try/except 等价。
        jsonl_log.append_line(_file_for_date(datetime.now()), row, logger=_log)

    def cleanup_old_logs(self, *, days: int = RETAIN_DAYS) -> int:
        """启动时跑一次;超过 days 天的 jsonl 文件删除(D7 锁)。"""
        return jsonl_log.cleanup_files_by_name_date(
            AUDIT_DIR, "approvals-*.jsonl",
            prefix="approvals-", days=days, logger=_log,
        )


# 模块级单例
_audit: AuditLog | None = None


def get_audit_log() -> AuditLog:
    global _audit
    if _audit is None:
        _audit = AuditLog(session_id="")
    return _audit


def _reset_audit() -> None:
    global _audit
    _audit = None
