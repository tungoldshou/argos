"""LedgerEntry — 单条行为账本条目(spec §6 信任面)。

设计约束:
- frozen dataclass — 不可变;落盘后任何修改都是新条目。
- undo 三态(UndoState):available / done / impossible
- reversible 三态(Reversible):yes / no / unknown
- receipt_sig:HMAC 回执签名前 16 字符截断 —— 供独立核验,不存全文
  (避免泄漏完整 HMAC,防止将来算法升级时旧签名被滥用;截断足以审计一致性)。
- undo_token:reversible=yes 时本期记录 run 级 tar 快照路径(str 绝对路径);
  实际还原由 RunSnapshot.restore() 负责。reversible≠yes 时为 None。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

# 三态可逆性(spec §6 信任面)
Reversible = Literal["yes", "no", "unknown"]

# 撤销状态(spec §6 信任面)
UndoState = Literal["available", "done", "impossible"]


@dataclass(frozen=True, slots=True)
class LedgerEntry:
    """单条行为账本条目。

    字段语义:
      ts            — Unix 时间戳(float,来自 Receipt.ts)
      run_id        — 所属 run 的 id(12 hex)
      seq           — 本 run 内的顺序号(从 1 起,严格递增)
      action        — 动作名(来自 Receipt.action,如 "write_file" / "run_shell")
      summary_human — 人话一句描述(确定性模板生成,不调模型)
                      例: "写入了 report.md(+120 行)"
      risk          — 风险级别("low" / "medium" / "high")
      reversible    — 可逆性三态("yes" / "no" / "unknown")
      undo_token    — reversible=yes 时为快照 tar 文件绝对路径;否则 None
      receipt_sig   — Receipt.sig 前 16 字符截断(供审计核验签名一致性)
      undo_state    — 撤销状态("available" / "done" / "impossible")
    """
    ts: float
    run_id: str
    seq: int
    action: str
    summary_human: str
    risk: str                         # "low" | "medium" | "high"
    reversible: Reversible
    undo_token: str | None            # reversible=yes → 快照 tar 路径;否则 None
    receipt_sig: str                  # Receipt.sig[:16](截断,供审计)
    undo_state: UndoState

    def to_dict(self) -> dict:
        """序列化为 dict(供 JSONL 落盘)。"""
        return {
            "ts": self.ts,
            "run_id": self.run_id,
            "seq": self.seq,
            "action": self.action,
            "summary_human": self.summary_human,
            "risk": self.risk,
            "reversible": self.reversible,
            "undo_token": self.undo_token,
            "receipt_sig": self.receipt_sig,
            "undo_state": self.undo_state,
        }

    @staticmethod
    def from_dict(d: dict) -> "LedgerEntry":
        """从 JSONL 落盘 dict 还原 LedgerEntry。"""
        return LedgerEntry(
            ts=float(d["ts"]),
            run_id=str(d["run_id"]),
            seq=int(d["seq"]),
            action=str(d["action"]),
            summary_human=str(d["summary_human"]),
            risk=str(d["risk"]),
            reversible=d["reversible"],  # type: ignore[arg-type]
            undo_token=d.get("undo_token"),
            receipt_sig=str(d["receipt_sig"]),
            undo_state=d["undo_state"],  # type: ignore[arg-type]
        )

    def with_undo_state(self, state: UndoState) -> "LedgerEntry":
        """返回新的 LedgerEntry,undo_state 已更新(frozen dataclass 不可变,返回副本)。"""
        import dataclasses
        return dataclasses.replace(self, undo_state=state)
