"""AuditLog:append-only JSONL,30 天滚动清理,IO 失败 continue(spec §2.7)。"""
from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

_log = logging.getLogger("argos.permissions.audit")

AUDIT_DIR: Path = Path(os.path.expanduser("~/.argos/audit"))
RETAIN_DAYS: int = 30


def _file_for_date(d: datetime) -> Path:
    return AUDIT_DIR / f"approvals-{d.strftime('%Y-%m-%d')}.jsonl"


@dataclass
class AuditLog:
    session_id: str

    def _ensure_dir(self) -> None:
        try:
            AUDIT_DIR.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            _log.warning("permissions audit: 创建目录失败 %s:%s", AUDIT_DIR, e)

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
        self._ensure_dir()
        try:
            f = _file_for_date(datetime.now())
            with f.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(row, ensure_ascii=False) + "\n")
        except OSError as e:
            _log.warning("permissions audit: append 失败:%s", e)

    def cleanup_old_logs(self, *, days: int = RETAIN_DAYS) -> int:
        """启动时跑一次;超过 days 天的 jsonl 文件删除(D7 锁)。"""
        if not AUDIT_DIR.exists():
            return 0
        cutoff = datetime.now() - timedelta(days=days)
        removed = 0
        try:
            for f in AUDIT_DIR.glob("approvals-*.jsonl"):
                # 解析文件名日期
                try:
                    date_str = f.stem.replace("approvals-", "")
                    file_date = datetime.strptime(date_str, "%Y-%m-%d")
                except ValueError:
                    continue
                if file_date < cutoff:
                    try:
                        f.unlink()
                        removed += 1
                    except OSError as e:
                        _log.warning("permissions audit: cleanup %s 失败:%s", f, e)
        except OSError as e:
            _log.warning("permissions audit: cleanup 扫描失败:%s", e)
        return removed


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
