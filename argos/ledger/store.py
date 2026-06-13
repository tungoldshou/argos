"""LedgerStore — JSONL 追加写 + 回放(spec §6 信任面)。

存储路径: ~/.argos/ledger/<run_id>.jsonl
格式: 每行一条 LedgerEntry.to_dict() 序列化的 JSON。

设计约束(沿用 jsonl_log.py 风格):
- IO 失败 → log warning + 不抛(best-effort 语义;账本丢失不阻断主流程)。
- 追加写(append),不加全局锁(单进程 best-effort)。
- replay 按 seq 排序返回,保持幂等性。
- undo_complete 更新最后一条 reversible=yes/undo_state=available 的条目到 done,
  写一条 undo_done 标记条目(供回放区分)。
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

from argos.ledger.entry import LedgerEntry, UndoState

log = logging.getLogger("argos.ledger")

# 默认账本根目录
_LEDGER_ROOT = Path.home() / ".argos" / "ledger"


class LedgerStore:
    """JSONL 账本:单 run 追加写 + 回放。

    线程/进程安全:best-effort(不加跨进程锁)。
    """

    def __init__(self, ledger_dir: Path | None = None) -> None:
        self._root = Path(ledger_dir) if ledger_dir else _LEDGER_ROOT

    def _path(self, run_id: str) -> Path:
        return self._root / f"{run_id}.jsonl"

    def append(self, entry: LedgerEntry) -> None:
        """追加一条 LedgerEntry 到 JSONL 文件。IO 失败 log warning + 不抛。"""
        p = self._path(entry.run_id)
        try:
            p.parent.mkdir(parents=True, exist_ok=True)
            line = json.dumps(entry.to_dict(), ensure_ascii=False) + "\n"
            with p.open("a", encoding="utf-8") as fh:
                fh.write(line)
        except OSError as e:
            log.warning("ledger: append 失败 %s: %s", p, e)

    def replay(self, run_id: str) -> list[LedgerEntry]:
        """回放 run_id 的账本,按 seq 排序返回 LedgerEntry 列表。

        文件不存在 → 返空列表(不抛)。
        解析失败的行 → log warning + 跳过。
        """
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
        """把该 run 所有 undo_state=available 的条目标记为 done,追加一条 undo_done 标记。

        返回 True = 至少有一条标记成功;False = 无可标记条目(用于诚实拒 409)。
        实现:重写文件(把 available → done);然后追加 undo_done 标记。
        best-effort:读写失败 log + 返 False。
        """
        entries = self.replay(run_id)
        available = [e for e in entries if e.undo_state == "available"]
        if not available:
            return False

        # 更新内存中的条目状态
        updated = [
            e.with_undo_state("done") if e.undo_state == "available" else e
            for e in entries
        ]

        # 覆写文件
        p = self._path(run_id)
        try:
            p.parent.mkdir(parents=True, exist_ok=True)
            with p.open("w", encoding="utf-8") as fh:
                for e in updated:
                    fh.write(json.dumps(e.to_dict(), ensure_ascii=False) + "\n")
                # 追加 undo_done 标记条目(特殊 action=undo_done,seq=0 作哨兵)
                marker = {
                    "ts": __import__("time").time(),
                    "run_id": run_id,
                    "seq": 0,
                    "action": "undo_done",
                    "summary_human": "撤销完成:已还原 run 起点的文件改动。",
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
        """判断该 run 的 undo 是否已完成(含 undo_done 标记)。"""
        entries = self.replay(run_id)
        return any(e.action == "undo_done" for e in entries)

    def get_entry(self, run_id: str, seq: int) -> "LedgerEntry | None":
        """按 seq 取单条 LedgerEntry;不存在返 None。"""
        for e in self.replay(run_id):
            if e.seq == seq:
                return e
        return None

    def mark_entry_done(self, run_id: str, seq: int) -> bool:
        """将指定 seq 条目的 undo_state 从 available 改为 done,覆写文件。

        返回 True = 成功找到并标记;False = 条目不存在或状态不是 available。
        best-effort:IO 失败 log + 返 False。
        """
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
