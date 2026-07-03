from __future__ import annotations

import json
import logging
from pathlib import Path

from argos.ledger.entry import LedgerEntry, UndoState
from argos.i18n import t

log = logging.getLogger("argos.ledger")


def _default_ledger_root() -> Path:
    from argos import config

    return Path(config.get("ARGOS_CONFIG_DIR") or (Path.home() / ".argos")).expanduser() / "ledger"


class LedgerStore:

    def __init__(self, ledger_dir: Path | None = None) -> None:
        self._root = Path(ledger_dir) if ledger_dir else _default_ledger_root()

    def _path(self, run_id: str) -> Path:
        return self._root / f"{run_id}.jsonl"

    def append(self, entry: LedgerEntry) -> None:
        p = self._path(entry.run_id)
        try:
            p.parent.mkdir(parents=True, exist_ok=True)
            line = json.dumps(entry.to_dict(), ensure_ascii=False) + "\n"
            with p.open("a", encoding="utf-8") as fh:
                fh.write(line)
        except OSError as e:
            log.warning("ledger: append 失败 %s: %s", p, e)

    def replay(self, run_id: str) -> list[LedgerEntry]:
        p = self._path(run_id)
        if not p.exists():
            return []
        entries: list[LedgerEntry] = []
        try:
            with p.open("r", encoding="utf-8") as fh:
                for i, line in enumerate(fh, 1):
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        d = json.loads(line)
                        entries.append(LedgerEntry.from_dict(d))
                    except Exception as e:  # noqa: BLE001
                        log.warning("ledger: replay 第 %d 行解析失败 (%s): %s", i, p, e)
        except OSError as e:
            log.warning("ledger: replay 读取失败 %s: %s", p, e)
        entries.sort(key=lambda e: (e.seq, e.ts))
        return entries

    def undo_complete(self, run_id: str) -> bool:
        entries = self.replay(run_id)
        available = [e for e in entries if e.undo_state == "available"]
        if not available:
            return False

        updated = [
            e.with_undo_state("done") if e.undo_state == "available" else e
            for e in entries
        ]

        p = self._path(run_id)
        try:
            p.parent.mkdir(parents=True, exist_ok=True)
            with p.open("w", encoding="utf-8") as fh:
                for e in updated:
                    fh.write(json.dumps(e.to_dict(), ensure_ascii=False) + "\n")
                marker = {
                    "ts": __import__("time").time(),
                    "run_id": run_id,
                    "seq": 0,
                    "action": "undo_done",
                    "summary_human": t("core2.ledger.undo_done"),
                    "risk": "low",
                    "reversible": "no",
                    "undo_token": None,
                    "receipt_sig": "",
                    "undo_state": "done",
                }
                fh.write(json.dumps(marker, ensure_ascii=False) + "\n")
        except OSError as e:
            log.warning("ledger: undo_complete 写入失败 %s: %s", p, e)
            return False
        return True

    def is_undo_done(self, run_id: str) -> bool:
        entries = self.replay(run_id)
        return any(e.action == "undo_done" for e in entries)

    def get_entry(self, run_id: str, seq: int) -> "LedgerEntry | None":
        for e in self.replay(run_id):
            if e.seq == seq:
                return e
        return None

    def mark_entry_done(self, run_id: str, seq: int) -> bool:
        entries = self.replay(run_id)
        target = None
        for e in entries:
            if e.seq == seq:
                target = e
                break
        if target is None or target.undo_state != "available":
            return False

        updated = [
            e.with_undo_state("done") if e.seq == seq else e
            for e in entries
        ]
        p = self._path(run_id)
        try:
            p.parent.mkdir(parents=True, exist_ok=True)
            with p.open("w", encoding="utf-8") as fh:
                for e in updated:
                    fh.write(json.dumps(e.to_dict(), ensure_ascii=False) + "\n")
        except OSError as e:
            log.warning("ledger: mark_entry_done 写入失败 %s seq=%d: %s", p, seq, e)
            return False
        return True
